"""Edge-case, vulnerability and telemetry-consistency suite.

    python tests/test_edge_cases.py

A  boundary limits (tower, coordinates, tilt, area, duration, slope, dates) - accepted at the edge, rejected just beyond it
B  error handler: malformed / hostile requests always return a clean HTTP 422 with a per-field message, never a crash
C  missing or inconsistent telemetry inputs
D  out-of-range warnings
E  telemetry consistency when switching Most Safety / Balanced / Most Power
F  dynamic tower height: exact horizon, and its effect on sunlight, Earth contact, slope and the verdict
G  NASA / JPL benchmark (nasa_benchmark.py)
H  front-end error handling and physics helpers (frontend/src/lib, evaluated in Node)

Writes outputs/test_edge_cases_report.json; exit code 1 on any failure.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np

os.environ["LUNAR_SKIP_BG_WARMUP"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))
sys.path.insert(0, str(ROOT / "src" / "analysis"))
from fastapi.testclient import TestClient  # noqa: E402

import api_server  # noqa: E402
import mission_simulator as ms  # noqa: E402
import nasa_benchmark as nb  # noqa: E402
import predict_site as ps  # noqa: E402

CLIENT = TestClient(api_server.app, raise_server_exceptions=False).__enter__()  # a server crash shows up as HTTP 500, which a case can assert on
BEST, OTHER = "Auto_SP_099", "Auto_SP_075"
MODES = ("most_safety", "balanced", "most_power")
JSON_HDR = {"content-type": "application/json"}
CASES: list[tuple[str, str, callable]] = []
_CACHE: dict = {}


def case(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def expect(ok, detail=""):
    if not ok:
        raise AssertionError(detail or "condition false")
    return detail


def post(path, body=None, **kw):
    return CLIENT.post(path, json=body, **kw) if body is not None else CLIENT.post(path, **kw)


def ev(**body):
    key = json.dumps(body, sort_keys=True)
    if key not in _CACHE:
        r = post("/api/evaluate", body)
        _CACHE[key] = (r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else None)
    return _CACHE[key]


# ======================================================================================= A. boundary limits
ACCEPT = [  # (field, value) that must be accepted (HTTP 200), with a preset site
    ("tower_height_m", 1), ("tower_height_m", 150), ("tower_height_m", 75.5), ("panel_tilt_deg", 0), ("panel_tilt_deg", 90),
    ("panel_area_m2", 1), ("panel_area_m2", 50), ("duration_hours", 1), ("duration_hours", 1440), ("max_slope_deg", 0), ("max_slope_deg", 15),
    ("min_sun_pct", 0), ("min_sun_pct", 100), ("min_earth_pct", 0), ("min_earth_pct", 100), ("duration_days", 60),
]
REJECT = [  # just beyond the limit: must be HTTP 422
    ("tower_height_m", 0.99), ("tower_height_m", 150.01), ("tower_height_m", 0), ("tower_height_m", -10), ("tower_height_m", 1e9),
    ("panel_tilt_deg", -0.01), ("panel_tilt_deg", 90.01), ("panel_area_m2", 0.99), ("panel_area_m2", 50.01),
    ("duration_hours", 0), ("duration_hours", 1442), ("duration_days", 0), ("duration_days", 60.2), ("max_slope_deg", 15.01), ("max_slope_deg", -1),
    ("min_sun_pct", 100.1), ("min_earth_pct", -0.1),
]


def _accept(field, value):
    def fn():
        code, j = ev(site_id=BEST, **{field: value})
        return expect(code == 200 and "primary_landing_decision" in j, f"HTTP {code}")
    return fn


def _reject(field, value):
    def fn():
        r = post("/api/evaluate", {"site_id": BEST, field: value})
        j = r.json()
        return expect(r.status_code == 422 and field in r.text and j.get("errors"), f"HTTP {r.status_code}: {r.text[:100]}")
    return fn


for _f, _v in ACCEPT:
    case("A", f"accepts {_f} = {_v}")(_accept(_f, _v))
for _f, _v in REJECT:
    case("A", f"rejects {_f} = {_v} with HTTP 422 naming the field")(_reject(_f, _v))

for _lat, _lon, _ok in [(-90, 0, True), (-85, 360, True), (-87.5, 0, True), (-84.999, 10, False), (-90.001, 10, False), (-87, -0.001, False), (-87, 360.001, False)]:
    def _mk(la=_lat, lo=_lon, ok=_ok):
        def fn():
            r = post("/api/evaluate", {"lat": la, "lon": lo, "duration_hours": 24}, params=None)
            return expect((r.status_code == 200) == ok and (ok or r.status_code == 422), f"HTTP {r.status_code}")
        return fn
    case("A", f"coordinates ({_lat}, {_lon}) {'accepted' if _ok else 'rejected'}")(_mk())


@case("A", "window beyond the end of the 60-day baseline is rejected with a clear message")
def _():
    r = post("/api/evaluate", {"site_id": BEST, "start_datetime_utc": "2027-01-11T00:00:00Z", "duration_hours": 200})
    return expect(r.status_code == 422 and "baseline" in r.text, r.text[:120])


@case("A", "start date before the baseline is rejected")
def _():
    r = post("/api/evaluate", {"site_id": BEST, "start_datetime_utc": "2026-11-01T00:00:00Z", "duration_hours": 24})
    return expect(r.status_code == 422, str(r.status_code))


@case("A", "longitude 0 and 360 describe the same point (same verdict and score)")
def _():
    a, b = ev(lat=-87.5, lon=0, duration_hours=24)[1], ev(lat=-87.5, lon=360, duration_hours=24)[1]
    return expect(a["primary_landing_decision"]["Suitability_Score"] == b["primary_landing_decision"]["Suitability_Score"])


# ======================================================================================= B. error handler
BAD_BODIES = {
    "NaN tower": '{"site_id":"Auto_SP_099","tower_height_m":NaN}', "-Infinity area": '{"site_id":"Auto_SP_099","panel_area_m2":-Infinity}',
    "Infinity longitude": '{"lat":-87,"lon":Infinity}', "empty body": "", "plain text": "hello", "JSON array": "[1,2]", "JSON string": '"x"',
    "truncated JSON": '{"site_id":"Auto_SP_099",', "null": "null", "wrong types": '{"site_id":123,"tower_height_m":"tall"}',
}


def _bad_body(raw):
    def fn():
        bad = []
        for path in ("/api/evaluate", "/api/compare", "/api/export-csv"):
            r = CLIENT.post(path, content=raw, headers=JSON_HDR)
            try:
                j = r.json()
                clean = r.status_code == 422 and isinstance(j.get("detail"), (list, str)) and (j.get("errors") is not None or isinstance(j["detail"], str))
            except ValueError:
                clean = False
            if not clean:
                bad.append((path, r.status_code, r.text[:50]))
        return expect(not bad, str(bad))
    return fn


for _n, _raw in BAD_BODIES.items():
    case("B", f"malformed request '{_n}': clean HTTP 422 JSON on evaluate, compare and export-csv")(_bad_body(_raw))


@case("B", "error body lists each bad field with a plain-language message and a summary")
def _():
    r = post("/api/evaluate", {"site_id": BEST, "tower_height_m": 999, "panel_tilt_deg": 200, "panel_area_m2": 0})
    j = r.json()
    fields = {e["field"] for e in j["errors"]}
    return expect(r.status_code == 422 and fields == {"tower_height_m", "panel_tilt_deg", "panel_area_m2"} and "between 1 and 150 m" in j["summary"], j["summary"])


@case("B", "wrong HTTP method / unknown path give clean 4xx, never 500")
def _():
    codes = [CLIENT.get("/api/evaluate").status_code, CLIENT.get("/api/nope").status_code, CLIENT.delete("/api/health").status_code]
    return expect(all(400 <= c < 500 for c in codes), str(codes))


@case("B", "hostile site_id strings are rejected cleanly (SQL / path / huge / unicode)")
def _():
    bad = []
    for sid in ["'; DROP TABLE sites;--", "../../etc/passwd", "A" * 5000, "Auto_SP_099\x00", "🚀", "<script>alert(1)</script>"]:
        r = post("/api/evaluate", {"site_id": sid})
        if r.status_code not in (422, 400):
            bad.append((sid[:15], r.status_code))
    return expect(not bad, str(bad))


# ======================================================================================= C. missing telemetry inputs
@case("C", "unknown site id gives HTTP 422 with the id in the message")
def _():
    r = post("/api/evaluate", {"site_id": "Auto_SP_999"})
    return expect(r.status_code == 422 and "Auto_SP_999" in r.text, r.text[:100])


@case("C", "request with no location gives HTTP 422 asking for site_id or lat+lon")
def _():
    r = post("/api/evaluate", {"duration_hours": 24})
    return expect(r.status_code == 422 and "site_id" in r.text, r.text[:120])


@case("C", "latitude without longitude is rejected")
def _():
    return expect(post("/api/evaluate", {"lat": -87}).status_code == 422)


@case("C", "compare with a missing scenario is rejected cleanly")
def _():
    r = post("/api/compare", {"scenario_a": {"site_id": BEST}})
    return expect(r.status_code == 422 and "scenario_b" in r.text, r.text[:100])


@case("C", "timeline hour index past the end of the window is rejected")
def _():
    return expect(post("/api/evaluate", {"site_id": BEST, "duration_hours": 24, "timeline_hour_index": 24}).status_code == 422)


@case("C", "every successful evaluation contains all telemetry blocks the dashboard reads")
def _():
    need = ["primary_landing_decision", "terrain_topography_physics", "solar_illumination_visibility", "earth_communication_status", "timeline", "scenario", "xai_and_hazard_alerts"]
    bad = [s for s in (BEST, OTHER, "Auto_SP_46") if any(k not in ev(site_id=s, duration_hours=240)[1] for k in need)]
    return expect(not bad, str(bad))


@case("C", "timeline arrays all have the mission length and no NaN / None values")
def _():
    j = ev(site_id=BEST, duration_hours=240)[1]["timeline"]
    n = {k: len(v) for k, v in j.items()}
    clean = all(all(x is not None and not (isinstance(x, float) and not math.isfinite(x)) for x in v) for v in j.values())
    return expect(set(n.values()) == {240} and clean, str(n))


@case("C", "GET /api/sites and /api/health stay available and complete")
def _():
    h, s = CLIENT.get("/api/health"), CLIENT.get("/api/sites")
    return expect(h.status_code == 200 and s.status_code == 200 and s.json()["n_sites"] == 100)


# ======================================================================================= D. out-of-range warnings
@case("D", "unfamiliar slope is flagged out of range; visibility above the maximum is not")
def _():
    import pandas as pd
    tr = pd.read_csv(ROOT / "outputs" / "terrain_corrected_dataset.csv").iloc[0]
    rg = float(pd.read_csv(ROOT / "outputs" / "site_roughness.csv").set_index("Site_ID")["Roughness_m"][tr["Site_ID"]])
    raw = {f: float(tr[f]) for f in ps.FEATURES} | {"Roughness_m": rg}
    prof = ps.resolve_profile(None, 15.0, 25.0, 20.0)

    def run(**o):
        return ps.assess_features(float(tr["Lat"]), float(tr["Lon"]), raw | o, {"ephemeris": "t", "terrain": "t"}, [], prof, explain_result=False)
    from predict_site import _dataset
    steep = run(Slope_deg=float(_dataset()["Slope_deg"].max()) + 5.0)  # beyond any slope the model was trained on
    bright = run(Sun_Visible_Pct=100.0, Earth_Visible_Pct=100.0)
    return expect("Slope_deg" in steep["ood_features"] and not bright["ood_warning"], f"steep {steep['ood_features']}; bright {bright['ood_features']}")


@case("D", "out-of-range result carries a readable OOD warning in the alerts list")
def _():
    import pandas as pd
    tr = pd.read_csv(ROOT / "outputs" / "terrain_corrected_dataset.csv").iloc[0]
    raw = {f: float(tr[f]) for f in ps.FEATURES} | {"Slope_deg": float(ps._dataset()["Slope_deg"].max()) + 5.0}
    out = ps.assess_features(float(tr["Lat"]), float(tr["Lon"]), raw, {"ephemeris": "t", "terrain": "t"}, [], ps.resolve_profile(None, 15.0, 25.0, 20.0), explain_result=False)
    return expect(any(w.startswith("OOD") for w in out["warnings"]) and out["Safety_Class"] == "Hazardous", str(out["warnings"][:2]))


@case("D", "ood_warning is a boolean in every API evaluation (presets and clicked points)")
def _():
    vals = [ev(site_id=BEST)[1]["xai_and_hazard_alerts"]["ood_warning"], ev(lat=-88.1, lon=77.0, duration_hours=72)[1]["xai_and_hazard_alerts"]["ood_warning"]]
    return expect(all(isinstance(v, bool) for v in vals), str(vals))


@case("D", "hard guardrails fire on extreme inputs: 70 deg slope is Unsafe even with the best hardware")
def _():
    import pandas as pd
    tr = pd.read_csv(ROOT / "outputs" / "terrain_corrected_dataset.csv").iloc[0]
    raw = {f: float(tr[f]) for f in ps.FEATURES} | {"Slope_deg": 70.0, "Sun_Visible_Pct": 100.0, "Earth_Visible_Pct": 100.0}
    out = ps.assess_features(float(tr["Lat"]), float(tr["Lon"]), raw, {"ephemeris": "t", "terrain": "t"}, [], ps.resolve_profile(None, 15.0, 25.0, 20.0), explain_result=False)
    return expect(out["Safety_Class"] == "Hazardous" and out["Suitability_Score"] <= 44.0, f"{out['Safety_Class']} {out['Suitability_Score']}")


# ======================================================================================= E. mode consistency
MODE_SITES = [BEST, OTHER, "Auto_SP_073", "Auto_SP_072", "Auto_SP_46", "Auto_SP_07", "Auto_SP_01", "Auto_SP_058"]


def by_mode(site):
    return {m: ev(site_id=site, priority_mode=m, duration_hours=1440)[1] for m in MODES}


@case("E", "hourly telemetry is identical in all three modes (Sun, Earth, power) for 8 sites")
def _():
    bad = []
    for s in MODE_SITES:
        r = by_mode(s)
        keys = ("sun_el_eff_deg", "earth_el_eff_deg", "power_watts", "illumination_state", "dte_status")
        if any(r[m]["timeline"][k] != r["balanced"]["timeline"][k] for m in MODES for k in keys):
            bad.append(s)
    return expect(not bad, str(bad))


@case("E", "the safety verdict is identical in all three modes for 8 sites")
def _():
    bad = [s for s in MODE_SITES if len({by_mode(s)[m]["primary_landing_decision"]["Safety_Class"] for m in MODES}) != 1]
    return expect(not bad, str(bad))


@case("E", "terrain, sunlight and Earth metrics are identical in all modes")
def _():
    bad = []
    for s in MODE_SITES:
        r = by_mode(s)
        sig = {m: (r[m]["terrain_topography_physics"]["Slope_deg"], r[m]["solar_illumination_visibility"]["Sun_Visible_Pct"], r[m]["earth_communication_status"]["Earth_Visible_Pct"]) for m in MODES}
        if len(set(sig.values())) != 1:
            bad.append(s)
    return expect(not bad, str(bad))


@case("E", "each mode reports its own weights (60/25/15, 40/35/25, 20/60/20) and they sum to 1")
def _():
    want = {"most_safety": (0.6, 0.25, 0.15), "balanced": (0.4, 0.35, 0.25), "most_power": (0.2, 0.6, 0.2)}
    r = by_mode(BEST)
    got = {m: tuple(r[m]["primary_landing_decision"]["mode_weights"][k] for k in ("terrain", "solar", "comms")) for m in MODES}
    return expect(got == want and all(abs(sum(w) - 1) < 1e-12 for w in got.values()), str(got))


@case("E", "score shift between modes equals the change in weights x component scores (non-capped sites)")
def _():
    bad = []
    for s in (BEST, OTHER):
        r = by_mode(s)
        cs = r["balanced"]["xai_and_hazard_alerts"]["component_scores"]
        for m in ("most_safety", "most_power"):
            w, b = ps.mode_weights(m), ps.mode_weights("balanced")
            shift = sum((w[i] - b[i]) * cs[k] for i, k in enumerate(("terrain", "solar", "comms")))
            got = r[m]["primary_landing_decision"]["Suitability_Score"] - r["balanced"]["primary_landing_decision"]["Suitability_Score"]
            if abs(got - shift) > 0.02:
                bad.append((s, m, round(got, 3), round(shift, 3)))
    return expect(not bad, str(bad))


@case("E", "Unsafe verdicts stay capped at 44 and every score stays in 0-100 in all modes (all 100 sites)")
def _():
    import pandas as pd
    ids = pd.read_csv(ROOT / "final_lunar_dataset_fixed.csv")["Site_ID"].tolist()
    bad = []
    for s in ids:
        for m in MODES:
            p = ev(site_id=s, priority_mode=m, duration_hours=1440)[1]["primary_landing_decision"]
            if not (0 <= p["Suitability_Score"] <= 100) or (p["Safety_Class"] == "Hazardous" and p["Suitability_Score"] > 44.0):
                bad.append((s, m, p["Suitability_Score"]))
    return expect(not bad, str(bad[:4]))


@case("E", "/api/sites ranking is a valid 1..100 permutation in every mode and changes between modes")
def _():
    orders = {}
    for m in MODES:
        j = CLIENT.get("/api/sites", params={"priority_mode": m}).json()
        ranks = sorted(s["rank"] for s in j["sites"])
        if ranks != list(range(1, 101)):
            raise AssertionError(f"{m}: ranks not 1..100")
        orders[m] = [s["site_id"] for s in sorted(j["sites"], key=lambda s: s["rank"])][:10]
    return expect(len({tuple(v) for v in orders.values()}) >= 2, "mode changes nothing in the ranking")


@case("E", "CSV export telemetry rows are identical across modes")
def _():
    texts = {m: post("/api/export-csv", {"site_id": BEST, "priority_mode": m, "duration_hours": 48}).text for m in MODES}
    body = lambda t: [ln for ln in t.splitlines() if ln[:4].isdigit() or ln.startswith("20")]  # hourly rows only
    return expect(len({tuple(body(t)) for t in texts.values()}) == 1)


@case("E", "invalid mode name is rejected with HTTP 422")
def _():
    return expect(post("/api/evaluate", {"site_id": BEST, "priority_mode": "turbo"}).status_code == 422)


# ======================================================================================= F. dynamic tower height
TOWERS = (1, 5, 20, 50, 100, 150)


def tw(h, site=BEST):
    return ev(site_id=site, tower_height_m=h, duration_hours=1440)[1]


@case("F", "reported horizon dip equals the exact formula acos(R/(R+h)) for every tower height")
def _():
    bad = [h for h in TOWERS if abs(tw(h)["solar_illumination_visibility"]["tower_horizon_boost_deg"] - math.degrees(math.acos(1737400.0 / (1737400.0 + h)))) > 1e-4]
    return expect(not bad, str(bad))


@case("F", "hourly Sun and Earth elevations never drop as the mast grows (horizon re-ray-traced from the mast top)")
def _():
    bad = []
    for key in ("sun_el_eff_deg", "earth_el_eff_deg"):
        prev = np.array(tw(TOWERS[0])["timeline"][key])
        for h in TOWERS[1:]:
            cur = np.array(tw(h)["timeline"][key])
            if (cur < prev - 1e-3).any():
                bad.append((key, h))
            prev = cur
    return expect(not bad, str(bad))


@case("F", "mast benefit is re-ray-traced from the mast top, and reported with the no-mast reference values")
def _():
    j = tw(150)
    s, c = j["solar_illumination_visibility"], j["earth_communication_status"]
    method = s["terrain_horizon"].get("mast_method", "")
    return expect("re-ray-traced" in method and s["Sun_Visible_Pct"] >= s["Sun_Visible_Pct_no_mast"] and c["Earth_Visible_Pct"] >= c["Earth_Visible_Pct_no_mast"],
                  f"{method}; sun {s['Sun_Visible_Pct_no_mast']} -> {s['Sun_Visible_Pct']}")


@case("F", "sunlight and Earth contact never decrease as the tower gets taller (3 sites)")
def _():
    bad = []
    for s in (BEST, OTHER, "Auto_SP_073"):
        sun = [tw(h, s)["solar_illumination_visibility"]["Sun_Visible_Pct"] for h in TOWERS]
        earth = [tw(h, s)["earth_communication_status"]["Earth_Visible_Pct"] for h in TOWERS]
        if any(b < a - 1e-9 for a, b in zip(sun, sun[1:])) or any(b < a - 1e-9 for a, b in zip(earth, earth[1:])):
            bad.append(s)
    return expect(not bad, str(bad))


@case("F", "terrain slope and elevation are identical at every tower height (a mast cannot change the ground)")
def _():
    sig = {h: (tw(h)["terrain_topography_physics"]["Slope_deg"], tw(h)["terrain_topography_physics"]["Elevation_m"]) for h in TOWERS}
    return expect(len(set(sig.values())) == 1, str(sig))


@case("F", "solar power and mission energy never decrease with tower height")
def _():
    e = [sum(tw(h)["timeline"]["power_watts"]) for h in TOWERS]
    return expect(all(b >= a - 1e-6 for a, b in zip(e, e[1:])) and e[-1] > e[0], str([round(x) for x in e]))


@case("F", "changing the tower re-runs the verdict pipeline (score and horizon change; same site, same terrain)")
def _():
    a, b = tw(1)["primary_landing_decision"]["Suitability_Score"], tw(150)["primary_landing_decision"]["Suitability_Score"]
    return expect(a != b, f"{a} vs {b}")


@case("F", "tower height propagates to the CSV export (hourly Sun elevation) and is echoed in the response")
def _():
    j = tw(120)
    rows = post("/api/export-csv", {"site_id": BEST, "tower_height_m": 120, "duration_hours": 1440}).text.splitlines()[1:]
    csv_sun = [float(r.split(",")[3]) for r in rows[:24]]
    return expect(j["scenario"]["hardware"]["tower_height_m"] == 120 and np.allclose(csv_sun, j["timeline"]["sun_el_eff_deg"][:24], atol=1e-3), "tower not applied in CSV")


# ======================================================================================= G. NASA / JPL benchmark
@case("G", "NASA benchmark: no strict check fails and at least 20 pass")
def _():
    rep = nb.run_benchmark()
    s = rep["summary"]
    fails = [c["name"] for c in rep["checks"] if c["status"] == "FAIL"]
    return expect(s["FAIL"] == 0 and s["PASS"] >= 20, f"{s['PASS']} pass, {s['FAIL']} fail {fails}")


@case("G", "NASA benchmark covers terrain, illumination, ephemeris, constants, geometry, scoring and solar physics")
def _():
    groups = {c["group"] for c in json.loads((ROOT / "outputs" / "nasa_benchmark.json").read_text())["checks"]}
    need = {"terrain", "illumination", "ephemeris", "constants", "geometry", "scoring", "solar"}
    return expect(need <= groups, f"missing {need - groups}")


@case("G", "NASA benchmark does not hide uncertainty: the slope comparison is reported as INFO with its reason")
def _():
    slope = [c for c in json.loads((ROOT / "outputs" / "nasa_benchmark.json").read_text())["checks"] if "slope" in c["name"].lower()]
    return expect(slope and slope[0]["status"] == "INFO" and "scale" in slope[0]["detail"].lower(), str(slope[:1]))


@case("G", "GET /api/benchmark serves the report")
def _():
    r = CLIENT.get("/api/benchmark")
    return expect(r.status_code == 200 and r.json()["summary"]["FAIL"] == 0, str(r.status_code))


@case("G", "benchmark thresholds are not vacuous: a corrupted reference makes a check fail")
def _():
    saved = dict(nb.NASA_CONSTANTS)
    nb.NASA_CONSTANTS["Moon mean radius (m)"] = (ms.R_MOON_M, 1_700_000.0, 0.0)  # pretend the reference differs
    try:
        nb.CHECKS.clear()
        nb.check_constants_and_geometry()
        failed = [c for c in nb.CHECKS if c["status"] == "FAIL"]
    finally:
        nb.NASA_CONSTANTS.clear()
        nb.NASA_CONSTANTS.update(saved)
        nb.CHECKS.clear()
    return expect(len(failed) == 1, f"{len(failed)} failing checks")


# ======================================================================================= H. front-end error handling (Node)
def js_edge() -> dict:
    if "js" not in _CACHE:
        node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(ev(site_id=BEST)[1], f)
        r = subprocess.run([node, str(ROOT / "tests" / "js_edge.mjs"), f.name], capture_output=True, text=True, cwd=ROOT, timeout=120)
        os.unlink(f.name)
        if r.returncode:
            raise AssertionError(f"js_edge.mjs failed: {r.stderr[-300:]}")
        _CACHE["js"] = json.loads(r.stdout)
    return _CACHE["js"]


for _field in ("tower", "lat", "lon", "tilt", "area"):
    def _mk_js(field=_field):
        def fn():
            b = js_edge()["boundaries"][field]
            return expect(all(b.values()), f"wrong: {[k for k, ok in b.items() if not ok]}")
        return fn
    case("H", f"browser validation: {_field} accepts the edge values and rejects blank / NaN / Infinity / out-of-range")(_mk_js())


@case("H", "browser limits equal the backend limits (tower 150, lat -90..-85, lon 0..360, tilt 0..90, area 1..50)")
def _():
    return expect(all(js_edge()["limitsMatchBackend"].values()), str(js_edge()["limitsMatchBackend"]))


@case("H", "validation messages name the field and its allowed range")
def _():
    return expect(js_edge()["messageNamesFieldAndLimit"])


@case("H", "validateScenario passes a good scenario and reports every bad field at once")
def _():
    j = js_edge()
    return expect(j["validateScenarioClean"] and j["validateScenarioFindsAll"] == "area,lat,lon,tilt,tower", j["validateScenarioFindsAll"])


@case("H", "a complete backend result passes the telemetry check; every required field exists in a real result")
def _():
    j = js_edge()
    return expect(j["realOk"] and j["requiredFieldsExistInRealResult"])


@case("H", "removing ANY required telemetry field is detected and named (no crash)")
def _():
    return expect(js_edge()["everyMissingFieldDetected"])


@case("H", "NaN score, empty timeline and garbage objects are all handled without throwing")
def _():
    j = js_edge()
    return expect(j["nanScoreDetected"] and j["emptyTimelineDetected"] and j["garbageNeverThrows"])


@case("H", "errors are classified (input / offline / unexpected) and always carry advice for the user")
def _():
    k = js_edge()["errorKinds"]
    return expect(k["input"] == "input" and k["offline"] == "offline" and k["offline5xx"] == "offline" and k["unexpected"] == "unexpected"
                  and k["incomplete"] == "incomplete" and k["nullErr"] == "unexpected" and js_edge()["errorHasAdvice"] and js_edge()["incompleteListsMissing"], str(k))


@case("H", "browser horizon distance equals sqrt(2Rh + h^2) and the dip equals the independent geometry (1-150 m)")
def _():
    j = js_edge()
    return expect(j["horizonDistanceMatchesTangent"] and j["dipMatchesIndependent"] and j["horizonGrowsWithHeight"], str(j["horizonDistanceKm"]))


def main() -> int:
    results = []
    for n, (g, name, fn) in enumerate(CASES, 1):
        try:
            detail, ok = fn() or "", True
        except AssertionError as exc:
            detail, ok = str(exc), False
        except Exception as exc:  # an unexpected crash is a failure, shown with its location
            detail, ok = f"{type(exc).__name__}: {exc} @ {traceback.extract_tb(exc.__traceback__)[-1].lineno}", False
        results.append({"n": n, "group": g, "case": name, "pass": ok, "detail": detail})
        print(f"{n:3d} [{'PASS' if ok else 'FAIL'}] {g} · {name}" + (f"  — {detail}" if detail else ""), flush=True)
    passed = sum(r["pass"] for r in results)
    print(f"\n==== {passed}/{len(results)} cases passed ====")
    (ROOT / "outputs" / "test_edge_cases_report.json").write_text(json.dumps({"passed": passed, "total": len(results), "cases": results}, indent=1), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
