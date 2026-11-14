"""Regression tests: a taller mast must never downgrade a verdict; Optimal slope rule fixed at 5.0 deg; hardware-aware map.

    python tests/test_verdict_rules.py

Covers (1) no out-of-range downgrade when tower-driven visibility exceeds the training maximum, (2) the GO / Optimal slope limit
of <= 5.0 deg regardless of tower height, (3) the battery / tower safe-zone map (frontend/src/lib/hardwareMap.js, run in Node).
Writes outputs/test_verdict_rules_report.json; exit code 1 on any failure.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

os.environ["LUNAR_SKIP_BG_WARMUP"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))
sys.path.insert(0, str(ROOT / "src" / "analysis"))
from fastapi.testclient import TestClient  # noqa: E402

import api_server  # noqa: E402
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402

TR = pd.read_csv(ROOT / "outputs" / "terrain_corrected_dataset.csv")
RG = pd.read_csv(ROOT / "outputs" / "site_roughness.csv").set_index("Site_ID")["Roughness_m"]
IDS = TR["Site_ID"].tolist()
RANK = ps.CLASS_RANK
TOWERS = (1, 5, 20, 50, 150)
CASES: list[tuple[str, str, callable]] = []
CLIENT = TestClient(api_server.app).__enter__()
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


def verdict(site, tower):
    """Backend evaluation of a preset site (full 60-day window) at a tower height, cached."""
    key = (site, tower)
    if key not in _CACHE:
        _CACHE[key] = ms.evaluate_scenario(ms.Scenario(site_id=site, tower_height_m=tower, duration_hours=1440), include_timeline=False)
    return _CACHE[key]


def klass(site, tower):
    return verdict(site, tower)["primary_landing_decision"]["Safety_Class"]


def assess(row, mast_ref=False, **override):
    """Full pipeline on a site's (terrain-corrected) features; override simulates a mast raising visibility/elevations."""
    raw = {f: float(row[f]) for f in ps.FEATURES}
    raw["Roughness_m"] = float(RG[row["Site_ID"]])
    raw.update(override)
    if mast_ref:
        raw["_ood_ref"] = {f: float(row[f]) for f in ps.FEATURES}
    prof = ps.resolve_profile(None, 15.0, ps.DEFAULT_MIN_SUN_PCT, ps.DEFAULT_MIN_EARTH_PCT)
    return ps.assess_features(float(row["Lat"]), float(row["Lon"]), raw, {"ephemeris": "test", "terrain": "test"}, [], prof, explain_result=False)


def boosted(row, pts):
    """Features after a mast: visibility +pts (max 100), elevations +0.75 deg (the 150 m horizon dip)."""
    return dict(Sun_Visible_Pct=min(100.0, row["Sun_Visible_Pct"] + pts), Earth_Visible_Pct=min(100.0, row["Earth_Visible_Pct"] + pts),
                Sun_Avg_El=row["Sun_Avg_El"] + 0.75, Sun_Max_El=row["Sun_Max_El"] + 0.75,
                Earth_Avg_El=row["Earth_Avg_El"] + 0.75, Earth_Max_El=row["Earth_Max_El"] + 0.75)


def js_hw() -> dict:
    """Hardware-map results computed by the browser code (Node), cached."""
    if "js" not in _CACHE:
        node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
        r = subprocess.run([node, str(ROOT / "tests" / "js_hardware.mjs"), str(ROOT / "frontend" / "src" / "api" / "sitesData.json")],
                           capture_output=True, text=True, cwd=ROOT, timeout=180)
        if r.returncode:
            raise AssertionError(f"js_hardware.mjs failed: {r.stderr[-400:]}")
        _CACHE["js"] = json.loads(r.stdout)
    return _CACHE["js"]


# ===================================================================== 1. No out-of-range downgrade from tower visibility
@case("1", "visibility above the training maximum is not out of range (Sun 83.2 %, Earth 100 %)")
def _():
    out = assess(TR.iloc[0], Sun_Visible_Pct=83.2, Earth_Visible_Pct=100.0)
    return expect(not out["ood_warning"], str(out["ood_features"]))


@case("1", "visibility far above the maximum (100 %) adds no out-of-range flags in the batch check either")
def _():
    df = TR[ps.FEATURES].copy()
    base = int(ps.ood_mask(df).sum())
    df["Sun_Visible_Pct"] = 100.0
    df["Earth_Visible_Pct"] = 100.0
    after = int(ps.ood_mask(df).sum())
    return expect(after <= base, f"flagged {after} vs baseline {base}")


@case("1", "visibility BELOW the training minimum is still flagged (unfamiliar site)")
def _():
    out = assess(TR.iloc[0], Sun_Visible_Pct=-5.0)
    return expect("Sun_Visible_Pct" in out["ood_features"], str(out["ood_features"]))


@case("1", "slope above the training maximum is still flagged (only visibility is one-sided)")
def _():
    out = assess(TR.iloc[0], Slope_deg=float(TR["Slope_deg"].max()) + 8.0)
    return expect("Slope_deg" in out["ood_features"], str(out["ood_features"]))


def _make_boost_case(pts):
    def fn():
        bad, ood = [], 0
        for _, r in TR.iterrows():
            a = assess(r)
            b = assess(r, mast_ref=True, **boosted(r, pts))
            ood += int(b["ood_warning"])
            if RANK[b["Safety_Class"]] < RANK[a["Safety_Class"]]:
                bad.append(f"{r['Site_ID']}: {a['Safety_Class']}->{b['Safety_Class']}")
        return expect(not bad and ood == 0, f"downgrades {bad[:4]}; out-of-range warnings {ood}/100")
    return fn


for _pts in (10, 25, 40):
    case("1", f"mast-boosted features (+{_pts} pts visibility, +0.75 deg): no downgrade and no OOD on any of 100 sites")(_make_boost_case(_pts))


@case("1", "mast floor engages where the raw model would downgrade boosted features")
def _():
    hits = sum(int(assess(r, mast_ref=True, **boosted(r, 40))["safety_factor"]["mast_floor_applied"]) for _, r in TR.iterrows())
    return expect(hits >= 1, f"floor applied on {hits} sites")


@case("1", "all 100 sites x towers 1/5/20/50/150 m: verdict never gets worse as the mast grows")
def _():
    bad = []
    for i in IDS:
        ranks = [RANK[klass(i, t)] for t in TOWERS]
        if any(b < a for a, b in zip(ranks, ranks[1:])):
            bad.append((i, ranks))
    return expect(not bad, f"non-monotone: {bad[:4]}")


@case("1", "score never drops as the mast grows (all 100 sites, 1 -> 150 m, tolerance 1 pt)")
def _():
    worst = max(verdict(i, 1)["primary_landing_decision"]["Suitability_Score"] - verdict(i, 150)["primary_landing_decision"]["Suitability_Score"] for i in IDS)
    return expect(worst <= 1.0, f"largest drop {worst:+.2f} pts")


@case("1", "no out-of-range warning at 150 m on any of the 100 sites")
def _():
    flagged = [i for i in IDS if verdict(i, 150)["primary_landing_decision"]["ood_warning"]]
    return expect(not flagged, f"flagged {flagged[:5]}")


@case("1", "API: GO site Auto_SP_099 stays GO / Optimal at 150 m, with no OOD warning")
def _():
    out = {}
    for t in (5, 150):
        j = CLIENT.post("/api/evaluate", json={"site_id": "Auto_SP_099", "tower_height_m": t}).json()
        out[t] = (j["primary_landing_decision"]["mission_status_label"], j["xai_and_hazard_alerts"]["ood_warning"])
    return expect(all(v == ("GO / Optimal", False) for v in out.values()), str(out))


@case("1", "API: best site Auto_SP_075 stays GO at every tower height")
def _():
    labels = {t: CLIENT.post("/api/evaluate", json={"site_id": "Auto_SP_075", "tower_height_m": t}).json()["primary_landing_decision"]["mission_status_label"] for t in TOWERS}
    return expect(set(labels.values()) == {"GO / Optimal"}, str(labels))


@case("1", "clicked custom points: verdict at 150 m is never worse than at 5 m (60 random cap points)")
def _():
    rng = np.random.default_rng(11)
    bad = []
    for _ in range(60):
        lat, lon = float(-85 - 5 * rng.random()), float(360 * rng.random())
        v = [RANK[ms.evaluate_scenario(ms.Scenario(lat=lat, lon=lon, tower_height_m=t, duration_hours=720), include_timeline=False,
                                       series_mode="analytic")["primary_landing_decision"]["Safety_Class"]] for t in (5, 150)]
        if v[1] < v[0]:
            bad.append((round(lat, 3), round(lon, 3), v))
    return expect(not bad, f"downgrades {bad[:3]}")


# ===================================================================== 2. Optimal slope threshold fixed at 5.0 deg
@case("2", "Optimal slope limit is exactly 5.0 deg (backend constant)")
def _():
    return expect(ps.OPTIMAL_MAX_SLOPE_DEG == 5.0, str(ps.OPTIMAL_MAX_SLOPE_DEG))


@case("2", "Optimal slope limit is 5.0 deg in the browser engine too")
def _():
    return expect(js_hw()["optimalMaxSlope"] == 5.0)


@case("2", "no site is Optimal with slope above 5.0 deg at any tower height (backend, 100 sites x 5 towers)")
def _():
    bad = [(i, t) for i in IDS for t in TOWERS if klass(i, t) == "Optimal" and verdict(i, t)["terrain_topography_physics"]["Slope_deg"] > 5.0]
    return expect(not bad, str(bad[:4]))


@case("2", "synthetic: slope 5.0 deg is still eligible for Optimal; 5.3 deg never is")
def _():
    r = TR[TR["Site_ID"] == "Auto_SP_075"].iloc[0]
    at5, at53 = assess(r, Slope_deg=5.0)["Safety_Class"], assess(r, Slope_deg=5.3)["Safety_Class"]
    return expect(at5 == "Optimal" and at53 != "Optimal", f"5.0 deg -> {at5}; 5.3 deg -> {at53}")


@case("2", "synthetic: a 150 m mast on a slope-5.3 deg site cannot make it Optimal")
def _():
    r = TR[TR["Site_ID"] == "Auto_SP_075"].iloc[0]
    out = assess(r, mast_ref=True, Slope_deg=5.3, **boosted(r, 40))["Safety_Class"]
    return expect(out != "Optimal", out)


@case("2", "safe (green) sites at 5 m stay green at 150 m (backend, all 100 sites)")
def _():
    lost = [i for i in IDS if klass(i, 5) == "Optimal" and klass(i, 150) != "Optimal"]
    return expect(not lost, f"lost green: {lost}")


@case("2", "green count never decreases with tower height (backend: 1 -> 150 m)")
def _():
    n = [sum(klass(i, t) == "Optimal" for i in IDS) for t in TOWERS]
    return expect(all(b >= a for a, b in zip(n, n[1:])), f"green counts {dict(zip(TOWERS, n))}")


@case("2", "hard guardrails unchanged: slope 16 deg is NO-GO even with a 150 m mast")
def _():
    r = TR.iloc[1]
    return expect(assess(r, mast_ref=True, Slope_deg=16.0, **boosted(r, 40))["Safety_Class"] == "Hazardous")


# ===================================================================== 3. Hardware-aware safe-zone map (tower + battery)
@case("3", "map: green count never decreases as tower height grows (1 -> 150 m) and rises overall")
def _():
    n = [js_hw()["tower"][str(t)]["Optimal"] for t in (1, 5, 20, 50, 100, 150)]
    return expect(all(b >= a for a, b in zip(n, n[1:])) and n[-1] > n[0], f"green counts {n}")


@case("3", "map: non-NO-GO count never decreases as tower height grows")
def _():
    n = [100 - js_hw()["tower"][str(t)]["Hazardous"] for t in (1, 5, 20, 50, 100, 150)]
    return expect(all(b >= a for a, b in zip(n, n[1:])), f"safe-or-conditional counts {n}")


@case("3", "map: a bigger battery never reduces the green zones (1 -> 1000 kWh)")
def _():
    n = [js_hw()["battery"][str(b)]["Optimal"] for b in (1, 5, 20, 50, 100, 200, 500, 1000)]
    return expect(all(b >= a for a, b in zip(n, n[1:])), f"green counts {n}")


@case("3", "map: increasing the battery does increase green zones (1 kWh -> 1000 kWh)")
def _():
    b = js_hw()["battery"]
    return expect(b["1"]["Optimal"] < b["1000"]["Optimal"], f"{b['1']['Optimal']} -> {b['1000']['Optimal']} green")


@case("3", "map: a depleted battery is reported as the reason a site is NO-GO")
def _():
    return expect("battery depleted" in js_hw()["lowBatteryReasons"], str(js_hw()["lowBatteryReasons"]))


@case("3", "map: a small battery can only downgrade sites, never upgrade any")
def _():
    return expect(js_hw()["batteryNeverUpgrades"] is True)


@case("3", "map: no site is green with slope above 5.0 deg, at any tower height")
def _():
    js, bad = js_hw(), []
    for t, cls in js["towerSites"].items():
        bad += [(i, t) for i, c in cls.items() if c == "Optimal" and js["slopes"][i] > 5.0]
    return expect(not bad, str(bad[:4]))


@case("3", "map vs backend (5 m): at least 90 of 100 sites get the same verdict")
def _():
    n = sum(js_hw()["towerSites"]["5"][i] == klass(i, 5) for i in IDS)
    return expect(n >= 90, f"{n}/100 agree")


@case("3", "map vs backend (150 m): at least 80 of 100 agree; map never calls a backend NO-GO site green")
def _():
    js = js_hw()["towerSites"]["150"]
    n = sum(js[i] == klass(i, 150) for i in IDS)
    false_green = [i for i in IDS if js[i] == "Optimal" and klass(i, 150) == "Hazardous"]
    return expect(n >= 80 and not false_green, f"{n}/100 agree; false green {false_green}")


@case("3", "map vs backend: every backend-green site is green on the map (5 m and 150 m)")
def _():
    miss = [(i, t) for t in (5, 150) for i in IDS if klass(i, t) == "Optimal" and js_hw()["towerSites"][str(t)][i] != "Optimal"]
    return expect(not miss, str(miss))


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
    (ROOT / "outputs" / "test_verdict_rules_report.json").write_text(json.dumps({"passed": passed, "total": len(results), "cases": results}, indent=1), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
