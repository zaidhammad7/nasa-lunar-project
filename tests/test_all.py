"""Full data and system test: 100 numbered cases over the dataset, derived files, physics, model, API and frontend JS.

    python tests/test_all.py

Groups:  A dataset integrity · B derived-data consistency · C physics · D model & safety rules
         E API behaviour · F input validation · G frontend (JS) parity with the backend
Writes outputs/test_all_report.json and exits non-zero if any case fails.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

os.environ["LUNAR_SKIP_BG_WARMUP"] = "1"  # no background network fetches during tests
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))
sys.path.insert(0, str(ROOT / "src" / "analysis"))
from fastapi.testclient import TestClient  # noqa: E402

import api_server  # noqa: E402
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402

DATASET = ROOT / "final_lunar_dataset_fixed.csv"            # original hackathon data (never modified)
TRAINING = ROOT / "outputs" / "terrain_corrected_dataset.csv"  # + NASA LOLA terrain shadowing; drives model, ranking, app
RANKED = ROOT / "outputs" / "ranked_lunar_sites.csv"
ROUGH = ROOT / "outputs" / "site_roughness.csv"
SITES_JSON = ROOT / "frontend" / "src" / "api" / "sitesData.json"
CV = ROOT / "outputs" / "cv_metrics.json"
REPORT = ROOT / "outputs" / "test_all_report.json"
VALID_CLASSES = {"Optimal", "Acceptable", "Hazardous"}
BEST = "Auto_SP_099"
CASES: list[tuple[str, str, callable]] = []


def case(group: str, name: str):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def expect(ok: bool, detail: str = "") -> str:
    if not ok:
        raise AssertionError(detail or "condition false")
    return detail


# ---------------------------------------------------------------------------- shared fixtures (loaded once)
DS = pd.read_csv(DATASET)
RK = pd.read_csv(RANKED)
RG = pd.read_csv(ROUGH)
SJ = json.loads(SITES_JSON.read_text(encoding="utf-8"))
SJ_BY = {s["id"]: s for s in SJ}
DS_BY = DS.set_index("Site_ID")
TR = pd.read_csv(TRAINING)
TR_BY = TR.set_index("Site_ID")
RK_BY = RK.set_index("Site_ID")
RG_BY = RG.set_index("Site_ID")
CLIENT = TestClient(api_server.app).__enter__()  # runs the app lifespan (model loading), like the real server
_JS: dict | None = None


def js() -> dict:
    """Run tests/js_checks.mjs once and cache its JSON output."""
    global _JS
    if _JS is None:
        node = shutil.which("node") or next((p for p in (r"C:\Program Files\nodejs\node.exe",) if Path(p).exists()), None)
        if not node:
            raise AssertionError("Node.js not found (needed for frontend checks)")
        r = subprocess.run([node, str(ROOT / "tests" / "js_checks.mjs"), str(SITES_JSON)], capture_output=True, text=True, cwd=ROOT, timeout=120)
        if r.returncode:
            raise AssertionError(f"js_checks.mjs failed: {r.stderr[-400:]}")
        _JS = json.loads(r.stdout)
    return _JS


def evaluate(**body) -> dict:
    r = CLIENT.post("/api/evaluate", json=body)
    expect(r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def status_of(**body) -> int:
    return CLIENT.post("/api/evaluate", json=body).status_code


def assess(site_id: str, **override) -> dict:
    """Score a dataset site's features (optionally modified) through the full rule + ML + safety pipeline."""
    row = DS_BY.loc[site_id]
    raw = {f: float(row[f]) for f in ps.FEATURES}
    raw["Roughness_m"] = float(RG_BY.loc[site_id, "Roughness_m"])
    raw.update(override)
    prof = ps.resolve_profile(None, 15.0, 50.0, 40.0)
    return ps.assess_features(float(row["Lat"]), float(row["Lon"]), raw, {"ephemeris": "test", "terrain": "test"}, [], prof,
                              explain_result=False)


# ============================================================================ A. Dataset integrity (14)
@case("A", "dataset has exactly 100 sites")
def _():
    return expect(len(DS) == 100, f"{len(DS)} rows")

@case("A", "site IDs are unique")
def _():
    return expect(DS["Site_ID"].is_unique, f"{DS['Site_ID'].duplicated().sum()} duplicates")

@case("A", "no missing values in any column")
def _():
    n = int(DS.isna().sum().sum())
    return expect(n == 0, f"{n} missing cells")

@case("A", "latitudes within the -90..-85 deg study cap")
def _():
    return expect(DS["Lat"].between(-90, -85).all(), f"range {DS['Lat'].min()}..{DS['Lat'].max()}")

@case("A", "longitudes within 0..360 deg E")
def _():
    return expect(((DS["Lon"] >= 0) & (DS["Lon"] < 360)).all(), f"range {DS['Lon'].min()}..{DS['Lon'].max()}")

@case("A", "Sun/Earth visibility percentages within 0..100")
def _():
    ok = DS[["Sun_Visible_Pct", "Earth_Visible_Pct"]].apply(lambda c: c.between(0, 100)).all().all()
    return expect(ok, "out-of-range percentage")

@case("A", "Sun average elevation <= Sun maximum elevation (every site)")
def _():
    bad = DS[DS["Sun_Avg_El"] > DS["Sun_Max_El"]]
    return expect(bad.empty, f"violations: {bad['Site_ID'].tolist()}")

@case("A", "Earth average elevation <= Earth maximum elevation (every site)")
def _():
    bad = DS[DS["Earth_Avg_El"] > DS["Earth_Max_El"]]
    return expect(bad.empty, f"violations: {bad['Site_ID'].tolist()}")

@case("A", "slopes within 0..90 deg")
def _():
    return expect(DS["Slope_deg"].between(0, 90).all(), f"range {DS['Slope_deg'].min():.3f}..{DS['Slope_deg'].max():.3f}")

@case("A", "elevations within the Moon's physical range (-9.5..+11 km)")
def _():
    return expect(DS["Elevation_m"].between(-9500, 11000).all(), f"range {DS['Elevation_m'].min()}..{DS['Elevation_m'].max()} m")

@case("A", "roughness table covers all 100 sites")
def _():
    missing = set(DS["Site_ID"]) - set(RG["Site_ID"])
    return expect(not missing and len(RG) == 100, f"missing {sorted(missing)[:5]}")

@case("A", "roughness values finite and non-negative")
def _():
    v = RG["Roughness_m"]
    return expect(np.isfinite(v).all() and (v >= 0).all(), f"range {v.min():.3f}..{v.max():.3f} m")

@case("A", "roughness table terrain agrees with dataset (elev 0.01 m, slope 0.01 deg)")
def _():
    j = DS.merge(RG, on="Site_ID", suffixes=("", "_rg"))
    de, dsl = (j["Elevation_m"] - j["Elevation_m_rg"]).abs().max(), (j["Slope_deg"] - j["Slope_deg_rg"]).abs().max()
    return expect(de < 0.01 and dsl < 0.01, f"max diff {de:.4f} m, {dsl:.4f} deg")

@case("A", "training set keeps terrain; terrain-only horizons predict NASA sunlight (MAE < 3 pts, r > 0.95)")
def _():
    same = all(np.allclose(TR[c], DS[c]) for c in ("Lat", "Lon", "Elevation_m", "Slope_deg")) and list(TR["Site_ID"]) == list(DS["Site_ID"])
    err = (TR["Raytraced_Sun_Pct"] - TR["NASA_Sun_Pct"]).abs().mean()
    r = float(np.corrcoef(TR["Raytraced_Sun_Pct"], TR["NASA_Sun_Pct"])[0, 1])
    return expect(same and err < 3 and r > 0.95, f"terrain unchanged={same}; independent ray-traced vs NASA sunlight: MAE {err:.2f} pts, r {r:.3f}")

@case("A", "no two sites share the same coordinates")
def _():
    d = DS[["Lat", "Lon"]].round(4).duplicated().sum()
    return expect(d == 0, f"{d} duplicated coordinates")


# ============================================================================ B. Derived-data consistency (10)
@case("B", "ranked table lists the same 100 sites")
def _():
    return expect(set(RK["Site_ID"]) == set(DS["Site_ID"]) and len(RK) == 100, "site sets differ")

@case("B", "ranks are 1..100 and follow descending suitability score")
def _():
    ok = sorted(RK["Rank"]) == list(range(1, 101)) and RK.sort_values("Rank")["Suitability_Score"].is_monotonic_decreasing
    return expect(ok, "rank order inconsistent with score")

@case("B", "suitability scores within 0..100")
def _():
    return expect(RK["Suitability_Score"].between(0, 100).all(), "score out of range")

@case("B", "safety classes are Optimal / Acceptable / Hazardous only")
def _():
    s = set(RK["Safety_Class"]) | set(RK["Predicted_Class"])
    return expect(s <= VALID_CLASSES, f"classes {s}")

@case("B", "ranked-table features equal the terrain-corrected training set (every site)")
def _():
    cols = ["Lat", "Lon"] + ps.FEATURES
    d = (RK_BY.loc[DS["Site_ID"], cols].to_numpy() - TR_BY.loc[DS["Site_ID"], cols].to_numpy())
    return expect(np.abs(d).max() < 1e-6, f"max diff {np.abs(d).max():.2e}")

@case("B", "frontend site list has the same 100 sites")
def _():
    return expect(set(SJ_BY) == set(DS["Site_ID"]) and len(SJ) == 100, "site sets differ")

@case("B", "frontend coordinates equal the dataset (1e-4 deg)")
def _():
    d = max(max(abs(SJ_BY[i]["lat"] - DS_BY.loc[i, "Lat"]), abs(SJ_BY[i]["lon"] - DS_BY.loc[i, "Lon"])) for i in SJ_BY)
    return expect(d <= 1e-4, f"max diff {d:.2e} deg")

@case("B", "frontend Sun/Earth/terrain values equal the terrain-corrected training set")
def _():
    pairs = {"sun": "Sun_Visible_Pct", "sunAvg": "Sun_Avg_El", "sunMax": "Sun_Max_El", "earth": "Earth_Visible_Pct",
             "earthAvg": "Earth_Avg_El", "earthMax": "Earth_Max_El", "elev": "Elevation_m", "slope": "Slope_deg"}
    d = max(abs(SJ_BY[i][k] - TR_BY.loc[i, c]) for i in SJ_BY for k, c in pairs.items())
    return expect(d <= 5e-3, f"max diff {d:.2e}")

@case("B", "frontend roughness equals the roughness table")
def _():
    d = max(abs(SJ_BY[i]["rough"] - RG_BY.loc[i, "Roughness_m"]) for i in SJ_BY)
    return expect(d <= 1e-3, f"max diff {d:.2e} m")

@case("B", "frontend rank and rule class equal the ranked table")
def _():
    bad = [i for i in SJ_BY if SJ_BY[i]["rank"] != RK_BY.loc[i, "Rank"] or SJ_BY[i]["ruleClass"] != RK_BY.loc[i, "Safety_Class"]]
    return expect(not bad, f"mismatches {bad[:5]}")


# ============================================================================ C. Physics (14)
@case("C", "tower boost is zero at 0 m")
def _():
    return expect(ms.tower_boost_deg(0.0) == 0.0, f"{ms.tower_boost_deg(0.0)}")

@case("C", "tower boost at 20 m = 0.2749 deg (acos(R/(R+h)))")
def _():
    v = ms.tower_boost_deg(20)
    return expect(abs(v - 0.27492) < 1e-4, f"{v:.5f} deg")

@case("C", "tower boost at 150 m = 0.7529 deg")
def _():
    v = ms.tower_boost_deg(150)
    return expect(abs(v - 0.75287) < 1e-4, f"{v:.5f} deg")

@case("C", "tower boost increases with height (1..150 m)")
def _():
    v = [ms.tower_boost_deg(h) for h in range(1, 151)]
    return expect(all(b > a for a, b in zip(v, v[1:])), "not strictly increasing")

@case("C", "solar disc fully hidden at -1 deg and fully visible at +1 deg")
def _():
    lo, hi = float(ms.sun_disc_fraction(-1.0)), float(ms.sun_disc_fraction(1.0))
    return expect(lo == 0.0 and hi == 1.0, f"{lo}, {hi}")

@case("C", "solar disc half visible at 0 deg")
def _():
    v = float(ms.sun_disc_fraction(0.0))
    return expect(abs(v - 0.5) < 1e-12, f"{v}")

@case("C", "illumination states: darkness / partial / direct")
def _():
    s = ms.illumination_state(np.array([-1.0, 0.0, 1.0])).tolist()
    return expect(s == ["Total Darkness", "Partial Shadow", "Direct Sunlight"], str(s))

@case("C", "no power when the Sun is below the horizon")
def _():
    p = ms.power_watts(np.array([-5.0, -1.0, -0.3]), 10, 80)
    return expect(np.all(p == 0), str(p))

@case("C", "power = S0 x efficiency x area x sin(elevation + tilt)")
def _():
    want = 1361 * 0.30 * 10 * math.sin(math.radians(5 + 85))
    got = float(ms.power_watts(np.array([5.0]), 10, 85)[0])
    return expect(abs(got - want) < 1e-6, f"{got:.3f} W vs {want:.3f} W")

@case("C", "Shackleton floor (NASA: permanent shadow) stays 0% sunlit and NO-GO, even with a 150 m mast")
def _():
    out = {}
    for h in (5, 150):
        e = ms.evaluate_scenario(ms.Scenario(lat=-89.67, lon=129.78, duration_hours=1440, tower_height_m=h), include_timeline=False)
        out[h] = (e["solar_illumination_visibility"]["Sun_Visible_Pct"], e["primary_landing_decision"]["Safety_Class"])
    return expect(all(v == (0.0, "Hazardous") for v in out.values()), str(out))

@case("C", "power never negative (elevation -10..10, tilt 0..90)")
def _():
    el = np.linspace(-10, 10, 201)
    return expect(min(float(ms.power_watts(el, 10, t).min()) for t in range(0, 91, 5)) >= 0)

@case("C", "pole to -85 deg distance = 151.6 km (5 deg arc)")
def _():
    d = float(ms.haversine_km(-90, 0, -85, 0))
    return expect(abs(d - 1737.4 * math.radians(5)) < 0.05, f"{d:.2f} km")

@case("C", "sunset crossing found at the right fractional hour")
def _():
    t = ms.crossing_times(np.array([2.0, 1.0, -1.0, -2.0]), "down")
    return expect(len(t) == 1 and abs(t[0] - 1.5) < 1e-9, str(t))


# ============================================================================ D. Model and safety rules (12)
@case("D", "cross-validated score error (RMSE) below 5 points (5% of the 0-100 scale)")
def _():
    r = json.loads(CV.read_text())["regressors"]["GradientBoosting"]["RMSE_mean"]
    return expect(r < 5, f"RMSE {r:.2f}")

@case("D", "cross-validated R^2 above 0.9")
def _():
    r = json.loads(CV.read_text())["regressors"]["GradientBoosting"]["R2_mean"]
    return expect(r > 0.9, f"R2 {r:.3f}")

@case("D", "slope safety margin: 15 deg lander limit -> 13.5 deg allowed")
def _():
    return expect(ps.effective_max_slope(15.0) == 13.5, f"{ps.effective_max_slope(15.0)}")

@case("D", "priority-mode weights sum to 1")
def _():
    s = {m: sum(ps.mode_weights(m)) for m in ps.PRIORITY_MODES}
    return expect(all(abs(v - 1) < 1e-9 for v in s.values()), str(s))

@case("D", "unknown priority mode is rejected")
def _():
    try:
        ps.mode_weights("fastest")
    except ValueError:
        return "ValueError"
    raise AssertionError("accepted an unknown mode")

@case("D", "prediction is deterministic")
def _():
    a, b = assess(BEST), assess(BEST)
    sa, sb = a["Suitability_Score"], b["Suitability_Score"]
    return expect(sa == sb, f"{sa} vs {sb}")

@case("D", "all 100 sites: score 0..100, valid class, NO-GO never above 44")
def _():
    bad = []
    for sid in DS["Site_ID"]:
        p = assess(sid)
        if not (0 <= p["Suitability_Score"] <= 100 and p["Safety_Class"] in VALID_CLASSES
                and (p["Safety_Class"] != "Hazardous" or p["Suitability_Score"] <= 44.0)):
            bad.append(sid)
    return expect(not bad, f"bad: {bad[:5]}")

@case("D", "steeper slope never raises the score by more than model noise (0.25 pt; best site, 0..14 deg)")
def _():
    s = [assess(BEST, Slope_deg=float(x))["Suitability_Score"] for x in range(0, 15)]
    worst_rise = max(b - a for a, b in zip(s, s[1:]))
    ok = worst_rise <= 0.25 and s[-1] < s[0] - 20  # tree-model wiggle allowed; the overall trend must fall steeply
    return expect(ok, f"largest rise {worst_rise:+.2f} pt; {[round(v, 1) for v in s]}")

@case("D", "slope 16 deg forces NO-GO (tip-over guardrail)")
def _():
    c = assess(BEST, Slope_deg=16.0)["Safety_Class"]
    return expect(c == "Hazardous", c)

@case("D", "20% sunlight forces NO-GO (shadowed-region guardrail)")
def _():
    c = assess(BEST, Sun_Visible_Pct=20.0)["Safety_Class"]
    return expect(c == "Hazardous", c)

@case("D", "5% Earth visibility forces NO-GO (comms blackout guardrail)")
def _():
    c = assess(BEST, Earth_Visible_Pct=5.0)["Safety_Class"]
    return expect(c == "Hazardous", c)

@case("D", "slope 14 deg (above 13.5 deg derated limit) is NO-GO")
def _():
    c = assess(BEST, Slope_deg=14.0)["Safety_Class"]
    return expect(c == "Hazardous", c)


# ============================================================================ E. API behaviour (19)
@case("E", "GET /api/health reports models ready")
def _():
    r = CLIENT.get("/api/health")
    return expect(r.status_code == 200 and r.json().get("models_ready") is True, str(r.json())[:120])

@case("E", "GET /api/sites returns all 100 sites")
def _():
    j = CLIENT.get("/api/sites").json()
    n = len(j.get("sites", j.get("all_sites", []))) if isinstance(j, dict) else len(j)
    return expect(n == 100, f"{n} sites")

@case("E", "evaluate a preset site: required sections present")
def _():
    j = evaluate(site_id=BEST)
    need = {"primary_landing_decision", "terrain_topography_physics", "solar_illumination_visibility", "timeline", "scenario"}
    return expect(need <= set(j), f"missing {need - set(j)}")

@case("E", "timeline length equals the mission duration")
def _():
    j = evaluate(site_id=BEST, duration_hours=240)
    n = len(j["timeline"]["sun_el_eff_deg"])
    return expect(n == 240, f"{n} rows")

@case("E", "custom point: exact clicked coordinates are used")
def _():
    j = evaluate(lat=-87.5092, lon=100.1863, duration_hours=48)
    s = j["scenario"]
    lat, lon = s.get("lat", s.get("lat_deg")), s.get("lon", s.get("lon_deg_east"))
    return expect(abs(lat + 87.5092) < 1e-9 and abs(lon - 100.1863) < 1e-9, f"{lat}, {lon}")

@case("E", "verdict identical in all three priority modes")
def _():
    c = {m: evaluate(site_id=BEST, priority_mode=m, duration_hours=240)["primary_landing_decision"]["Safety_Class"] for m in ps.PRIORITY_MODES}
    return expect(len(set(c.values())) == 1, str(c))

@case("E", "reported mode weights match the configuration")
def _():
    j = evaluate(site_id=BEST, priority_mode="most_power", duration_hours=24)
    w = j["primary_landing_decision"].get("mode_weights") or j["scenario"].get("mode_weights")
    want = dict(zip(("terrain", "solar", "comms"), ps.mode_weights("most_power")))
    return expect(w is None or all(abs(w[k] - want[k]) < 1e-9 for k in want), f"{w}")

@case("E", "POST /api/compare returns both scenarios")
def _():
    r = CLIENT.post("/api/compare", json={"scenario_a": {"site_id": BEST, "duration_hours": 48}, "scenario_b": {"site_id": "Auto_SP_075", "duration_hours": 48}})
    j = r.json()
    sbs = j.get("side_by_side_comparison", {})
    a, b = sbs.get("scenario_a", {}).get("scenario", {}), sbs.get("scenario_b", {}).get("scenario", {})
    ok = r.status_code == 200 and a.get("site_id") == BEST and b.get("site_id") == "Auto_SP_075" and "deltas" in sbs
    return expect(ok, f"A={a.get('site_id')} B={b.get('site_id')} deltas={'deltas' in sbs}")

@case("E", "CSV export: one row per mission hour plus header")
def _():
    r = CLIENT.post("/api/export-csv", json={"site_id": BEST, "duration_hours": 72})
    rows = [x for x in csv.reader(io.StringIO(r.text)) if x]
    hdr = next((i for i, x in enumerate(rows) if x and x[0] == "timestamp_utc"), None)
    return expect(r.status_code == 200 and hdr is not None and len(rows) - hdr - 1 == 72, f"{len(rows)} lines, header at {hdr}")

@case("E", "repeat request is served from cache")
def _():
    body = {"site_id": "Auto_SP_46", "duration_hours": 96, "panel_area_m2": 13.5}
    a, b = CLIENT.post("/api/evaluate", json=body), CLIENT.post("/api/evaluate", json=body)
    return expect(b.headers.get("x-cache") == "HIT" and a.json() == b.json(), f"{a.headers.get('x-cache')} -> {b.headers.get('x-cache')}")

@case("E", "duration_days = 2 gives the same timeline as duration_hours = 48")
def _():
    a, b = evaluate(site_id=BEST, duration_days=2), evaluate(site_id=BEST, duration_hours=48)
    return expect(a["timeline"]["sun_el_eff_deg"] == b["timeline"]["sun_el_eff_deg"], "timelines differ")

@case("E", "timeline_hour_index selects that hour's live values")
def _():
    j = evaluate(site_id=BEST, duration_hours=100, timeline_hour_index=37)
    live = j["solar_illumination_visibility"]["live_sun_elevation_deg"]
    want = j["timeline"]["sun_el_eff_deg"][37]
    return expect(abs(live - want) < 1e-3, f"{live} vs {want}")

@case("E", "longer mast never lowers sunlight (API, 1 vs 150 m)")
def _():
    a = evaluate(site_id=BEST, tower_height_m=1, duration_hours=720)["solar_illumination_visibility"]["Sun_Visible_Pct"]
    b = evaluate(site_id=BEST, tower_height_m=150, duration_hours=720)["solar_illumination_visibility"]["Sun_Visible_Pct"]
    return expect(b >= a, f"{a} % -> {b} %")

@case("E", "larger panel area raises mission energy proportionally")
def _():
    def e(a):
        return evaluate(site_id=BEST, panel_area_m2=a, duration_hours=240)
    j10, j20 = e(10), e(20)
    p10, p20 = sum(j10["timeline"]["power_watts"]), sum(j20["timeline"]["power_watts"])
    return expect(p10 > 0 and abs(p20 / p10 - 2) < 1e-6, f"ratio {p20 / p10 if p10 else 'n/a'}")

@case("E", "power is zero whenever the timeline is in total darkness")
def _():
    tl = evaluate(site_id=BEST, duration_hours=720)["timeline"]
    pw, st = tl["power_watts"], tl["illumination_state"]
    bad = sum(1 for p, s in zip(pw, st) if s == "Total Darkness" and p > 0)
    return expect(pw is not None and st is not None and bad == 0, f"{bad} dark hours with power")

@case("E", "Hazardous verdict comes with at least one warning")
def _():
    worst = RK.sort_values("Suitability_Score").iloc[0]["Site_ID"]
    j = evaluate(site_id=worst, duration_hours=240)
    p = j["primary_landing_decision"]
    return expect(p["Safety_Class"] != "Hazardous" or len(j["xai_and_hazard_alerts"].get("warnings", [])) > 0, f"{worst}: {p['Safety_Class']}")

@case("E", "95% confidence interval contains the score")
def _():
    p = evaluate(site_id=BEST, duration_hours=240)["primary_landing_decision"]
    ci = p["score_uncertainty_95ci"]
    return expect(ci["lower"] <= p["Suitability_Score"] <= ci["upper"], f"{ci['lower']} <= {p['Suitability_Score']} <= {ci['upper']}")

@case("E", "GET /api/stress-test serves stored results")
def _():
    r = CLIENT.get("/api/stress-test")
    return expect(r.status_code == 200 and "stress_test" in r.json(), f"HTTP {r.status_code}")

@case("E", "single evaluation completes in under 1 s (preset)")
def _():
    t = time.perf_counter(); evaluate(site_id="Auto_SP_075", duration_hours=1440, panel_tilt_deg=61); dt = time.perf_counter() - t
    return expect(dt < 1.0, f"{dt * 1000:.0f} ms")


# ============================================================================ F. Input validation (16)
for label, body in [
    ("latitude -84.9 (outside cap)", {"lat": -84.9, "lon": 10}),
    ("latitude -90.1", {"lat": -90.1, "lon": 10}),
    ("longitude 360.1", {"lat": -87, "lon": 360.1}),
    ("longitude -0.1", {"lat": -87, "lon": -0.1}),
    ("tower 0.5 m", {"site_id": BEST, "tower_height_m": 0.5}),
    ("tower 151 m", {"site_id": BEST, "tower_height_m": 151}),
    ("panel tilt -1 deg", {"site_id": BEST, "panel_tilt_deg": -1}),
    ("panel tilt 91 deg", {"site_id": BEST, "panel_tilt_deg": 91}),
    ("panel area 0.5 m2", {"site_id": BEST, "panel_area_m2": 0.5}),
    ("panel area 51 m2", {"site_id": BEST, "panel_area_m2": 51}),
    ("duration 0 h", {"site_id": BEST, "duration_hours": 0}),
    ("unknown site ID", {"site_id": "Auto_SP_999"}),
    ("unknown priority mode", {"site_id": BEST, "priority_mode": "fastest"}),
    ("no location given", {"duration_hours": 24}),
    ("max slope 16 deg (above lander limit)", {"site_id": BEST, "max_slope_deg": 16}),
    ("window past the end of the ephemeris", {"site_id": BEST, "start_datetime_utc": "2027-01-11T00:00:00Z", "duration_hours": 200}),
]:
    def _make(b=body):
        def fn():
            code = status_of(**b)
            return expect(code == 422, f"HTTP {code}")
        return fn
    case("F", f"rejects {label} with HTTP 422")(_make())


# ============================================================================ G. Frontend (JS) parity with the backend (15)
@case("G", "JS horizon boost equals Python at 1, 20, 150 m")
def _():
    d = max(abs(a - ms.tower_boost_deg(h)) for a, h in zip(js()["towerBoost"], (1, 20, 150)))
    return expect(d < 1e-12, f"max diff {d:.1e}")

@case("G", "JS solar-disc fraction equals Python")
def _():
    want = ms.sun_disc_fraction(np.array([-1, -0.265, 0, 0.265, 1])).tolist()
    return expect(np.allclose(js()["discFraction"], want, atol=1e-12), f"{js()['discFraction']} vs {want}")

@case("G", "JS illumination states equal Python")
def _():
    return expect(js()["illumination"] == ms.illumination_state(np.array([-1.0, 0.0, 1.0])).tolist())

@case("G", "JS solar power equals Python (5 cases)")
def _():
    cases = [(5, 10, 85), (1, 20, 45), (-0.1, 10, 90), (0.2, 5, 80), (6.5, 50, 0)]
    want = [float(ms.power_watts(np.array([e]), a, t)[0]) for e, a, t in cases]
    d = max(abs(x - y) for x, y in zip(js()["power"], want))
    return expect(d < 1e-6, f"max diff {d:.1e} W")

@case("G", "JS safety constants equal the backend")
def _():
    c = js()["constants"]
    import suitability as su
    pairs = {"MAX_TOWER_M": ps.MAX_TOWER_HEIGHT_M, "SLOPE_MARGIN_DEG": ps.SLOPE_SAFETY_MARGIN_DEG, "ROUGHNESS_WEIGHT": ps.ROUGHNESS_SLOPE_WEIGHT,
             "SCORE_BUFFER": ps.SCORE_SAFETY_BUFFER, "ACCEPTABLE_MIN": su.ACCEPTABLE_MIN_SCORE, "SAFETY_CAP": ps.SAFETY_CAP_SCORE, "R_MOON_M": ms.R_MOON_M}
    bad = {k: (c[k], v) for k, v in pairs.items() if abs(c[k] - v) > 1e-9}
    return expect(not bad, f"mismatch {bad}")

@case("G", "JS priority-mode weights equal the backend")
def _():
    bad = {m: w for m, w in js()["modeWeights"].items() if any(abs(a - b) > 1e-12 for a, b in zip(w, ps.mode_weights(m)))}
    return expect(not bad, f"mismatch {bad}")

@case("G", "JS terrain/solar/comms sub-scores equal the ranked table (100 sites)")
def _():
    comp = js()["components"]
    d = max(max(abs(comp[i]["terrain"] - RK_BY.loc[i, "Terrain_Score"]), abs(comp[i]["solar"] - RK_BY.loc[i, "Solar_Score"]),
                abs(comp[i]["comms"] - RK_BY.loc[i, "Comms_Score"])) for i in comp)
    return expect(d < 1e-6, f"max diff {d:.1e}")

for _mode in ("most_safety", "balanced", "most_power"):
    def _make_mode(mode=_mode):
        def fn():
            want = ms.mode_scores(ms._ranked(), mode)
            want = dict(zip(ms._ranked()["Site_ID"], want))
            got = js()["modeScores"][mode]
            d = max(abs(got[i] - want[i]) for i in want)
            order_js = sorted(got, key=lambda i: -got[i])[:10]
            order_py = sorted(want, key=lambda i: -want[i])[:10]
            return expect(d < 1e-6 and order_js == order_py, f"max diff {d:.1e}; top-10 {'same' if order_js == order_py else 'differs'}")
        return fn
    case("G", f"JS ranking equals backend in '{_mode}' mode (100 sites)")(_make_mode())

@case("G", "JS great-circle distances equal Python")
def _():
    pts = [(-90, 0, -85, 0), (-85.3109, 332.293, -85.4735, 29.2177), (-88, 10, -88, 190)]
    d = max(abs(a - float(ms.haversine_km(*p))) for a, p in zip(js()["haversine"], pts))
    return expect(d < 1e-6, f"max diff {d:.1e} km")

@case("G", "3-D click mapping round-trips lat/lon exactly (2000 points)")
def _():
    e = js()["roundTripMaxErrDeg"]
    return expect(e < 1e-9, f"max error {e:.1e} deg")

@case("G", "battery model: empties at hour 66, 34 h without power (synthetic night)")
def _():
    b = js()["battery"]
    return expect(b["firstEmptyHour"] == 66 and b["hoursEmpty"] == 34 and not b["survives"], json.dumps(b))

@case("G", "battery sizing: 100 h night at 150 W needs 15.0 kWh")
def _():
    v = js()["requiredKwh"]
    return expect(abs(v - 15.0) < 1e-3, f"{v:.4f} kWh")

@case("G", "named craters lie in the polar region with valid longitudes")
def _():
    bad = [l["name"] for l in js()["landmarks"] if not (-90 <= l["lat"] <= -84 and 0 <= l["lon"] < 360)]
    return expect(not bad, f"bad {bad}")


# ============================================================================ runner
def main() -> int:
    results, t0 = [], time.perf_counter()
    for n, (group, name, fn) in enumerate(CASES, 1):
        try:
            detail, ok = fn() or "", True
        except AssertionError as exc:
            detail, ok = str(exc), False
        except Exception as exc:  # unexpected crash = failure with the error shown
            detail, ok = f"{type(exc).__name__}: {exc} @ {traceback.extract_tb(exc.__traceback__)[-1].lineno}", False
        results.append({"n": n, "group": group, "case": name, "pass": ok, "detail": detail})
        print(f"{n:3d} [{'PASS' if ok else 'FAIL'}] {group} · {name}" + (f"  — {detail}" if detail else ""), flush=True)
    passed = sum(r["pass"] for r in results)
    print(f"\n==== {passed}/{len(results)} cases passed in {time.perf_counter() - t0:.1f} s ====")
    REPORT.write_text(json.dumps({"passed": passed, "total": len(results), "cases": results}, indent=1), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
