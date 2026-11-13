"""The five golden demo sites and their warm-up (cache population + hot evaluation).

Used by the API start-up routine, POST /api/warmup and the standalone warmup_demo.py script so
that every judge scenario answers from caches in milliseconds, even on slow venue Wi-Fi.

Cache layout (./ephemeris_cache/): real hourly Sun/Earth series (*.npz) for every demo site and,
for custom coordinates, the LOLA terrain read (terrain_*.json) so the DEM is not needed live.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ephemeris_series as es  # noqa: E402
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402

DEMO_SITES = [
    {"key": "A", "name": "Scenario A - Top Optimal Site", "site_id": "Auto_SP_46", "lat": -88.3448, "lon": 225.8806},
    {"key": "B", "name": "Scenario B - High-Comms Optimal Site (Compare)", "site_id": "Auto_SP_36", "lat": -87.7039, "lon": 339.4475},
    {"key": "C", "name": "Steep Rim 100% Sun Trap", "site_id": "Auto_SP_07", "lat": -89.1858, "lon": 71.5816},
    {"key": "D", "name": "Custom - Shackleton Dark PSR Floor", "site_id": None, "lat": -89.85, "lon": 0.0},
    {"key": "E", "name": "Custom - Shackleton Illuminated Rim", "site_id": None, "lat": -89.54, "lon": 197.0},
]


def demo_scenario(site: dict, **overrides) -> ms.Scenario:
    """Default-parameter scenario for a demo site (preset by id, custom by lat/lon)."""
    if site["site_id"]:
        return ms.Scenario(site_id=site["site_id"], **overrides)
    return ms.Scenario(lat=site["lat"], lon=site["lon"], **overrides)


def request_body(site: dict) -> dict:
    """The minimal /api/evaluate body a frontend sends when a demo site is first selected."""
    return {"site_id": site["site_id"]} if site["site_id"] else {"lat": site["lat"], "lon": site["lon"]}


def site_status(site: dict) -> dict:
    """Which caches exist for a site right now (no network, no computation)."""
    series = es.load_cache(site["lat"], site["lon"]) is not None
    terrain = True if site["site_id"] else es.load_terrain_cache(site["lat"], site["lon"]) is not None
    return {"key": site["key"], "name": site["name"], "series_cached": series, "terrain_cached": terrain,
            "fully_cached": series and terrain}


def cached_count() -> int:
    """Number of demo sites that can be served entirely from disk caches."""
    return sum(site_status(s)["fully_cached"] for s in DEMO_SITES)


def warm_site(site: dict, allow_live: bool = True, dem_blocking: bool = False) -> dict:
    """Populate caches for one demo site and time a cold and a hot evaluation.

    allow_live  : fetch missing Horizons series / DEM terrain over the network.
    dem_blocking: for custom coordinates, wait for the DEM (up to ~15 s) instead of falling back.
    Returns a status dict including the evaluation payload under "payload".
    """
    out = {**site_status(site), "name": site["name"], "lat_deg": site["lat"], "lon_deg_east": site["lon"], "errors": []}
    t0 = time.perf_counter()
    if not out["series_cached"] and allow_live:
        try:
            es.fetch_live(site["lat"], site["lon"])
        except Exception as exc:
            out["errors"].append(f"Horizons: {type(exc).__name__}: {str(exc)[:100]}")
    if not out["terrain_cached"] and allow_live:
        try:
            if dem_blocking and not ps.dem_ready():
                ps.warm_dem()
            es.save_terrain_cache(site["lat"], site["lon"], ps.get_terrain_metrics(site["lat"], site["lon"]))
        except Exception as exc:
            out["errors"].append(f"DEM: {type(exc).__name__}: {str(exc)[:100]}")
    out["cache_fill_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out.update({k: v for k, v in site_status(site).items() if k in ("series_cached", "terrain_cached", "fully_cached")})
    scn = demo_scenario(site)
    t1 = time.perf_counter()
    payload = ms.evaluate_scenario(scn)
    out["eval_cold_ms"] = round((time.perf_counter() - t1) * 1000, 1)
    t2 = time.perf_counter()
    ms.evaluate_scenario(scn)
    out["eval_hot_ms"] = round((time.perf_counter() - t2) * 1000, 1)
    d = payload["primary_landing_decision"]
    out.update({"series_source": payload["solar_illumination_visibility"]["ephemeris_source"],
                "terrain_source": payload["terrain_topography_physics"]["source"], "Safety_Class": d["Safety_Class"],
                "mission_status_label": d["mission_status_label"], "Suitability_Score": d["Suitability_Score"],
                "Sun_Visible_Pct": payload["solar_illumination_visibility"]["Sun_Visible_Pct"],
                "Earth_Visible_Pct": payload["earth_communication_status"]["Earth_Visible_Pct"],
                "Slope_deg": payload["terrain_topography_physics"]["Slope_deg"],
                "guardrails": d["guardrails"]["triggered"], "safety_layers": d["safety_factor"]["layers_triggered"],
                "payload": payload})
    return out


def warm_demo_sites(allow_live: bool = True, dem_blocking: bool = False, sites: list[dict] | None = None) -> list[dict]:
    """Warm every demo site sequentially (Horizons rejects concurrent requests)."""
    return [warm_site(s, allow_live, dem_blocking) for s in (sites or DEMO_SITES)]
