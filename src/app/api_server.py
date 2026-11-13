"""FastAPI backend for the Lunar Landing Site Navigator dashboard.

Run from the repo root:
    uvicorn src.app.api_server:app --host 0.0.0.0 --port 8000
or  python src/app/api_server.py

All science lives in src/analysis (mission_simulator, predict_site, ephemeris_series); this
module only validates HTTP input and shapes responses.

Endpoints
  GET  /api/health
  GET  /api/sites         ?max_slope_deg&min_sun_pct&min_earth_pct[&lat&lon]
  POST /api/evaluate      one scenario -> dashboard outputs 1-9, csv metadata, hourly timeline
  POST /api/compare       {scenario_a, scenario_b} -> output 10 (side_by_side_comparison)
  POST /api/export-csv    one scenario -> mission_telemetry_export.csv (output 11)
  GET  /api/stress-test   stress_test_results.json + cross-validation metrics
"""
from __future__ import annotations

import json
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402
from suitability import OUTPUTS_DIR  # noqa: E402


def _warm() -> None:
    """Load models/datasets and run one evaluation so the first real request is fast."""
    try:
        ps._load_models()
        ps._uncertainty_model()
        ms._dataset()
        ms._ranked()
        ms._roughness_table()
        ms.evaluate_scenario(ms.Scenario(site_id="Auto_SP_099"), include_timeline=False)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    _warm()  # blocking: the first request must not pay the ~4 s model/dataset load
    ps.warm_dem_async()  # remote DEM opens in the background (~15 s); custom points use the CSV fallback until then
    yield


app = FastAPI(title="Lunar Landing Site Navigator API", version="3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])


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
    min_sun_pct: float = Field(50.0, ge=0.0, le=100.0)
    min_earth_pct: float = Field(40.0, ge=0.0, le=100.0)
    # 4-6. Hardware
    tower_height_m: float = Field(5.0, ge=1.0, le=20.0)
    panel_tilt_deg: float = Field(45.0, ge=0.0, le=90.0)
    panel_area_m2: float = Field(10.0, ge=1.0, le=50.0)

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
                           panel_area_m2=self.panel_area_m2)


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
    return {"status": "ok", "dem_ready": ps.dem_ready(), "schema_version": "3.0",
            "baseline_window_utc": ["2026-11-13T00:00:00Z", "2027-01-12T00:00:00Z"]}


@app.get("/api/sites")
def sites(max_slope_deg: float = Query(15.0, ge=0, le=15), min_sun_pct: float = Query(50.0, ge=0, le=100),
          min_earth_pct: float = Query(40.0, ge=0, le=100), lat: float = Query(-90.0, ge=-90, le=-85),
          lon: float = Query(0.0, ge=0, le=360)):
    """All 100 preset sites (with passes_filters) + the Top 5 that satisfy the vehicle filters."""
    try:
        return _ok(ms.sites_overview(max_slope_deg, min_sun_pct, min_earth_pct, lat, lon))
    except ValueError as exc:
        raise _bad(exc)


@app.post("/api/evaluate")
def evaluate(body: ScenarioIn):
    """Full evaluation of one scenario, including the hourly timeline for slider scrubbing."""
    try:
        return _ok(ms.evaluate_scenario(body.to_scenario()))
    except ValueError as exc:
        raise _bad(exc)


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
