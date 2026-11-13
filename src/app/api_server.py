"""FastAPI backend for the Lunar Landing Site Navigator dashboard.

Run from the repo root:
    uvicorn src.app.api_server:app --host 0.0.0.0 --port 8000
or  python src/app/api_server.py

All science lives in src/analysis (mission_simulator, predict_site, ephemeris_series, demo_sites);
this module only validates HTTP input, shapes responses and runs the start-up warm-up.

Endpoints
  GET  /api/health        readiness: models, DEM, cached demo sites, safety factor, warm-up latency
  POST /api/warmup        synchronous warm-up of the DEM + the 5 golden demo sites
  GET  /api/sites         ?max_slope_deg&min_sun_pct&min_earth_pct[&lat&lon]
  POST /api/evaluate      one scenario -> dashboard outputs 1-9, csv metadata, hourly timeline
  POST /api/compare       {scenario_a, scenario_b} -> output 10 (side_by_side_comparison)
  POST /api/export-csv    one scenario -> mission_telemetry_export.csv (output 11)
  GET  /api/stress-test   stress_test_results.json + cross-validation metrics

Start-up warm-up (lifespan)
  synchronous : load models + ranked CSV, run a dummy batch inference, evaluate once, serve every
                already-cached demo site from memory  -> `warmup_latency_ms`
  background  : open the remote LOLA DEM and read a 3x3 window (dem_ready), then fetch any missing
                Horizons series / DEM terrain for the demo sites. Set LUNAR_SKIP_BG_WARMUP=1 to disable.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import demo_sites  # noqa: E402
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402
import terrain_illumination as ti  # noqa: E402
import horizon as hz  # noqa: E402
from suitability import OUTPUTS_DIR  # noqa: E402

RESPONSE_CACHE_MAX = 256
STATE: dict = {"models_ready": False, "warmup_latency_ms": None, "warmup_started": False, "bg_log": []}
_RESP_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_RESP_LOCK = threading.Lock()


# ----------------------------------------------------------------------------
# Response cache (pre-seeded with the demo sites)
# ----------------------------------------------------------------------------
def _cache_key(body_dict: dict) -> str:
    return json.dumps(body_dict, sort_keys=True, default=str)


def _cacheable(payload: dict) -> bool:
    """Never cache answers built from fallback data (they would outlive the DEM/Horizons coming online)."""
    return not any(("fallback" in v) or ("offline" in v) for v in payload.get("data_sources", {}).values())


def _cache_put(body_dict: dict, payload: dict) -> bool:
    if not _cacheable(payload):
        return False
    raw = json.dumps(ms.to_jsonable(payload)).encode()
    with _RESP_LOCK:
        _RESP_CACHE[_cache_key(body_dict)] = raw
        _RESP_CACHE.move_to_end(_cache_key(body_dict))
        while len(_RESP_CACHE) > RESPONSE_CACHE_MAX:
            _RESP_CACHE.popitem(last=False)
    return True


def _cache_get(body_dict: dict) -> bytes | None:
    with _RESP_LOCK:
        raw = _RESP_CACHE.get(_cache_key(body_dict))
        if raw is not None:
            _RESP_CACHE.move_to_end(_cache_key(body_dict))
        return raw


def _seed_demo(results: list[dict]) -> int:
    """Store each fully cached demo site's default evaluation payload; returns how many were stored."""
    n = 0
    for site, res in zip(demo_sites.DEMO_SITES, results):
        if res.get("fully_cached") and res.get("payload") is not None:
            key = ScenarioIn(**demo_sites.request_body(site)).model_dump(mode="json", exclude_none=True)
            n += _cache_put(key, res["payload"])
    return n


# ----------------------------------------------------------------------------
# Warm-up
# ----------------------------------------------------------------------------
def _warm_sync() -> float:
    """Blocking part of the warm-up. Returns elapsed ms."""
    import pandas as pd
    t0 = time.perf_counter()
    ps._load_models()
    ps._uncertainty_model()
    ms._ranked()
    ms._roughness_table()
    df = ps._dataset()
    ps.predict_batch(df[ps.FEATURES].head(64))  # warms scikit-learn / NumPy thread pools
    ms.evaluate_scenario(ms.Scenario(site_id="Auto_SP_099"), include_timeline=False)
    STATE["models_ready"] = True
    results = []
    for s in demo_sites.DEMO_SITES:  # fully cached sites are computed now (disk -> memory), the rest in the background
        results.append(demo_sites.warm_site(s, allow_live=False) if demo_sites.site_status(s)["fully_cached"]
                       else {"fully_cached": False})
    _seed_demo(results)
    return round((time.perf_counter() - t0) * 1000, 1)


def _bg_warm() -> None:
    """Background part: DEM open + 3x3 read, then fetch whatever the demo sites are still missing."""
    def dem():
        try:
            STATE["bg_log"].append({"dem": ps.warm_dem()})
        except Exception as exc:
            STATE["bg_log"].append({"dem_error": f"{type(exc).__name__}: {str(exc)[:120]}"})

    def sites():
        todo = [s for s in demo_sites.DEMO_SITES if not demo_sites.site_status(s)["fully_cached"]]
        for s in todo:
            try:
                res = demo_sites.warm_site(s, allow_live=True)
                _seed_demo([res if s2 is s else {"fully_cached": False} for s2 in demo_sites.DEMO_SITES])
                STATE["bg_log"].append({"site": s["key"], "cached": res["fully_cached"], "errors": res["errors"]})
            except Exception as exc:
                STATE["bg_log"].append({"site": s["key"], "error": f"{type(exc).__name__}: {str(exc)[:120]}"})

    threading.Thread(target=dem, name="dem-warm", daemon=True).start()
    threading.Thread(target=sites, name="demo-cache-fill", daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    STATE["warmup_started"] = True
    if not (ti.available() and hz.dem_available()):
        print("WARNING: NASA LOLA data missing (illumination maps in data/lola_illumination/ and/or the polar DEM in "
              "data/lola_dem/). Preset sites still use cached horizons; clicked points fall back to coarser shadowing. "
              "Run: python src/analysis/build_corrected_dataset.py", flush=True)
    STATE["warmup_latency_ms"] = _warm_sync()
    if os.environ.get("LUNAR_SKIP_BG_WARMUP") != "1":
        _bg_warm()
    yield


app = FastAPI(title="Lunar Landing Site Navigator API", version="3.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition", "X-Cache"])


# ----------------------------------------------------------------------------
# Request models (the 8 dashboard inputs)
# ----------------------------------------------------------------------------
class ScenarioIn(BaseModel):
    """One scenario: location, mission window, vehicle filters, hardware and timeline position."""
    # 1. Location: a preset site_id, or custom lat/lon
    site_id: str | None = Field(None, examples=["Auto_SP_099"])
    lat: float | None = Field(None, ge=-90.0, le=-85.0, description="deg, -90..-85")
    lon: float | None = Field(None, ge=0.0, le=360.0, description="deg east, 0..360")
    # 2. Mission window
    start_datetime_utc: datetime | None = Field(None, description="default 2026-11-13T00:00:00Z")
    duration_hours: float | None = Field(None, ge=1, le=1441)
    duration_days: float | None = Field(None, gt=0, le=60.1, description="alternative to duration_hours")
    # 7. Timeline slider (hour inside the mission window) or an absolute timestamp
    timeline_hour_index: int | None = Field(None, ge=0)
    timestamp_utc: datetime | None = None
    # 3. Vehicle constraints
    max_slope_deg: float = Field(15.0, ge=0.0, le=15.0)
    min_sun_pct: float = Field(ps.DEFAULT_MIN_SUN_PCT, ge=0.0, le=100.0)
    min_earth_pct: float = Field(ps.DEFAULT_MIN_EARTH_PCT, ge=0.0, le=100.0)
    # 4-6. Hardware
    tower_height_m: float = Field(5.0, ge=1.0, le=ps.MAX_TOWER_HEIGHT_M)
    panel_tilt_deg: float = Field(45.0, ge=0.0, le=90.0)
    panel_area_m2: float = Field(10.0, ge=1.0, le=50.0)
    # 0. Optimisation priority (terrain / solar / comms weights 60/25/15, 40/35/25, 20/60/20)
    priority_mode: Literal["most_safety", "balanced", "most_power"] = "balanced"

    @model_validator(mode="after")
    def _need_location(self):
        if self.site_id is None and (self.lat is None or self.lon is None):
            raise ValueError("provide site_id, or both lat and lon")
        return self

    def to_scenario(self) -> ms.Scenario:
        hours = (self.duration_hours if self.duration_hours is not None
                 else self.duration_days * 24.0 if self.duration_days is not None else float(ms.BASELINE_HOURS))
        return ms.Scenario(lat=self.lat, lon=self.lon, site_id=self.site_id, start_datetime_utc=self.start_datetime_utc,
                           duration_hours=hours, timeline_hour_index=self.timeline_hour_index,
                           timestamp_utc=self.timestamp_utc, max_slope_deg=self.max_slope_deg,
                           min_sun_pct=self.min_sun_pct, min_earth_pct=self.min_earth_pct,
                           tower_height_m=self.tower_height_m, panel_tilt_deg=self.panel_tilt_deg,
                           panel_area_m2=self.panel_area_m2, priority_mode=self.priority_mode)


class CompareIn(BaseModel):
    """Scenario A (Site A / Date A / Hardware A) vs Scenario B."""
    scenario_a: ScenarioIn
    scenario_b: ScenarioIn
    include_timeline: bool = False


def _ok(payload) -> JSONResponse:
    return JSONResponse(ms.to_jsonable(payload))


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "models_ready": bool(STATE["models_ready"]), "dem_ready": ps.dem_ready(),
            "cached_demo_sites": demo_sites.cached_count(), "demo_sites_total": len(demo_sites.DEMO_SITES),
            "safety_factor_active": ps.SAFETY_FACTOR_ACTIVE, "warmup_latency_ms": STATE["warmup_latency_ms"],
            "terrain_shadowing_ready": ti.available(), "horizon_dem_ready": hz.dem_available(),
            "dem_error": ps.dem_error(), "response_cache_entries": len(_RESP_CACHE), "schema_version": "3.1",
            "baseline_window_utc": ["2026-11-13T00:00:00Z", "2027-01-12T00:00:00Z"]}


@app.post("/api/warmup")
def warmup() -> dict:
    """Synchronous warm-up of the DEM and all 5 demo sites (can take ~1-2 min the first time: Horizons is ~7 s per body)."""
    t0 = time.perf_counter()
    dem: dict
    try:
        dem = {"ready": True, **ps.warm_dem()}
    except Exception as exc:
        dem = {"ready": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    results = demo_sites.warm_demo_sites(allow_live=True, dem_blocking=False)
    seeded = _seed_demo(results)
    sites = [{k: v for k, v in r.items() if k != "payload"} for r in results]
    return ms.to_jsonable({"status": "ok", "dem": dem, "sites": sites, "cached_demo_sites": demo_sites.cached_count(),
                           "payloads_seeded_in_response_cache": seeded, "dem_ready": ps.dem_ready(),
                           "total_ms": round((time.perf_counter() - t0) * 1000, 1)})


@app.get("/api/sites")
def sites(max_slope_deg: float = Query(15.0, ge=0, le=15), min_sun_pct: float = Query(ps.DEFAULT_MIN_SUN_PCT, ge=0, le=100),
          min_earth_pct: float = Query(ps.DEFAULT_MIN_EARTH_PCT, ge=0, le=100), lat: float = Query(-90.0, ge=-90, le=-85),
          lon: float = Query(0.0, ge=0, le=360),
          priority_mode: Literal["most_safety", "balanced", "most_power"] = Query("balanced")):
    """All 100 preset sites (with passes_filters) + the Top 5 that satisfy the vehicle filters (slope safety-derated)."""
    try:
        return _ok(ms.sites_overview(max_slope_deg, min_sun_pct, min_earth_pct, lat, lon, priority_mode))
    except ValueError as exc:
        raise _bad(exc)


@app.post("/api/evaluate")
def evaluate(body: ScenarioIn):
    """Full evaluation of one scenario, including the hourly timeline for slider scrubbing."""
    key = body.model_dump(mode="json", exclude_none=True)
    hit = _cache_get(key)
    if hit is not None:
        return Response(hit, media_type="application/json", headers={"X-Cache": "HIT"})
    try:
        payload = ms.evaluate_scenario(body.to_scenario())
    except ValueError as exc:
        raise _bad(exc)
    _cache_put(key, payload)
    return Response(json.dumps(ms.to_jsonable(payload)).encode(), media_type="application/json", headers={"X-Cache": "MISS"})


@app.post("/api/compare")
def compare(body: CompareIn):
    """Scenario A vs Scenario B with exact numerical deltas (B - A)."""
    try:
        return _ok(ms.compare_scenarios(body.scenario_a.to_scenario(), body.scenario_b.to_scenario(),
                                        include_timeline=body.include_timeline))
    except ValueError as exc:
        raise _bad(exc)


@app.post("/api/export-csv")
def export_csv(body: ScenarioIn):
    """Hourly telemetry for the mission window as a downloadable CSV."""
    try:
        text = ms.build_csv(body.to_scenario())
    except ValueError as exc:
        raise _bad(exc)
    return StreamingResponse(iter([text]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="mission_telemetry_export.csv"'})


@app.get("/api/stress-test")
def stress_test():
    """Latest stress_test_results.json plus the cross-validation metrics of the models."""
    sp, cvp = OUTPUTS_DIR / "stress_test_results.json", OUTPUTS_DIR / "cv_metrics.json"
    if not sp.exists():
        raise HTTPException(status_code=404, detail="stress_test_results.json not found; run src/analysis/stress_test.py")
    cv = json.loads(cvp.read_text()) if cvp.exists() else None
    return JSONResponse({"stress_test": json.loads(sp.read_text()), "cross_validation": cv})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
