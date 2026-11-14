"""Benchmark of the simulation against NASA / JPL reference data, with explicit pass / fail thresholds.

    python src/analysis/nasa_benchmark.py        -> prints every check and writes outputs/nasa_benchmark.json

Reference data (all NASA or JPL; independent of our own model):
  * LOLA LDEM_75S_120M polar elevation model (PDS)          -> site elevation, terrain slope scale
  * LOLA AVGVISIB_85S_060M Sun / Earth average visibility   -> sunlight and Earth-contact percentages (via horizon_profiles.npz)
  * JPL Horizons hourly Sun / Earth elevations (cached)     -> ephemeris accuracy
  * NASA lunar fact sheet / SORCE constants                 -> radius, distance, periods, solar constant, obliquity
  * Geometry and energy conservation                        -> mast horizon, power bound, score weights

Each check has status PASS / FAIL, or INFO when a comparison is reported for transparency but cannot be a strict test (the
reason is stated). A check whose reference file is missing is SKIP, never silently PASS.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ephemeris_series as es  # noqa: E402
import horizon as hz  # noqa: E402
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402
import suitability as su  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "nasa_benchmark.json"
THRESHOLDS = {  # strict limits; the measured values are far inside them (see the report)
    "elevation_mae_m": 15.0, "elevation_r": 0.9999,
    "sun_mae_pts": 3.0, "sun_r": 0.95, "earth_mae_pts": 7.0, "earth_r": 0.95,
    "horizons_sun_rmse_deg": 0.15, "horizons_earth_rmse_deg": 0.8,
    "dip_formula_deg": 1e-9, "weights_sum": 1e-12, "mode_score_diff": 1e-9,
}
# NASA lunar fact sheet / SORCE values the model constants must equal (value, tolerance)
NASA_CONSTANTS = {
    "Moon mean radius (m)": (ms.R_MOON_M, 1_737_400.0, 0.0),
    "Total solar irradiance (W/m2)": (ms.SOLAR_CONSTANT_W_M2, 1361.0, 0.5),
    "Earth-Moon mean distance (km)": (es.EARTH_DISTANCE_KM, 384_400.0, 0.0),
    "Synodic month (days)": (es.P_SYNODIC_H / 24.0, 29.530589, 1e-6),
    "Draconic month (days)": (es.P_DRACONIC_H / 24.0, 27.212221, 1e-6),
    "Anomalistic month (days)": (es.P_ANOMALISTIC_H / 24.0, 27.554550, 1e-6),
    "Sun angular radius from the Moon (deg)": (ms.SUN_ANGULAR_RADIUS_DEG, 0.265, 0.01),
}
CHECKS: list[dict] = []


def add(group: str, name: str, status: str, value, reference: str, threshold: str = "", detail: str = "") -> None:
    CHECKS.append({"group": group, "name": name, "status": status, "value": value, "reference": reference, "threshold": threshold, "detail": detail})


def judge(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def sites() -> pd.DataFrame:
    return pd.read_csv(su.DATA_CSV)


# ------------------------------------------------------------------------------------------------ terrain
def check_terrain() -> None:
    d = sites()
    if not hz.dem_available():
        add("terrain", "Elevation vs NASA LOLA polar DEM", "SKIP", None, "LDEM_75S_120M", detail="data/lola_dem/ldem_75s_120m.img not found")
        return
    e = hz.height_m(d["Lat"].to_numpy(), d["Lon"].to_numpy())
    diff = e - d["Elevation_m"].to_numpy()
    mae, r = float(np.abs(diff).mean()), float(np.corrcoef(e, d["Elevation_m"])[0, 1])
    add("terrain", "Site elevation: mean absolute error vs NASA LOLA DEM (100 sites)", judge(mae < THRESHOLDS["elevation_mae_m"]),
        round(mae, 2), "LOLA LDEM_75S_120M", f"< {THRESHOLDS['elevation_mae_m']} m", f"max error {np.abs(diff).max():.1f} m")
    add("terrain", "Site elevation: correlation vs NASA LOLA DEM", judge(r > THRESHOLDS["elevation_r"]), round(r, 6), "LOLA LDEM_75S_120M", f"> {THRESHOLDS['elevation_r']}")

    # Slope depends on the baseline it is measured over: report the comparison, do not force a pass.
    m = hz._dem()

    def slope(lat, lon, step=120.0):
        line, samp = hz._to_pixel(lat, lon)
        i, j = int(round(line)), int(round(samp))
        z = m[i - 1:i + 2, j - 1:j + 2].astype(float) * hz.DN_TO_M
        dzdx = ((z[0, 2] + 2 * z[1, 2] + z[2, 2]) - (z[0, 0] + 2 * z[1, 0] + z[2, 0])) / (8 * step)
        dzdy = ((z[2, 0] + 2 * z[2, 1] + z[2, 2]) - (z[0, 0] + 2 * z[0, 1] + z[0, 2])) / (8 * step)
        return math.degrees(math.atan(math.hypot(dzdx, dzdy)))

    s = np.array([slope(a, b) for a, b in zip(d["Lat"], d["Lon"])])
    c = d["Slope_deg"].to_numpy()
    add("terrain", "Site slope: dataset vs slope from the 120 m polar DEM (Horn, 3x3)", "INFO",
        {"mean_dataset_deg": round(float(c.mean()), 2), "mean_polar_dem_deg": round(float(s.mean()), 2), "pearson_r": round(float(np.corrcoef(s, c)[0, 1]), 3)},
        "LOLA LDEM_75S_120M", "", "Slope is scale-dependent: the dataset slopes come from the finer global grid (about 10 m east-west near the pole) and "
        "are steeper than a 120 m grid shows. Correlation is moderate, so slope is the least certain input; lander-scale hazards need metre-scale maps.")


# ------------------------------------------------------------------------------------------------ illumination
def check_illumination() -> None:
    if not hz.PROFILES_NPZ.exists():
        add("illumination", "Sunlight / Earth visibility vs NASA LOLA illumination maps", "SKIP", None, "AVGVISIB_85S_060M", detail="horizon_profiles.npz missing")
        return
    z = np.load(hz.PROFILES_NPZ)
    for body, raw, nasa, mae_t, r_t in (("Sunlight", z["raw_sun_pct"], z["nasa_sun_pct"], THRESHOLDS["sun_mae_pts"], THRESHOLDS["sun_r"]),
                                        ("Earth visibility", z["raw_earth_pct"], z["nasa_earth_pct"], THRESHOLDS["earth_mae_pts"], THRESHOLDS["earth_r"])):
        mae, r = float(np.abs(raw - nasa).mean()), float(np.corrcoef(raw, nasa)[0, 1])
        note = "horizons ray-traced from terrain only; NASA illumination map not used as input"
        add("illumination", f"{body}: mean absolute error vs NASA LOLA map (100 sites)", judge(mae < mae_t), round(mae, 2), "AVGVISIB_85S_060M", f"< {mae_t} points", note)
        add("illumination", f"{body}: correlation vs NASA LOLA map", judge(r > r_t), round(r, 4), "AVGVISIB_85S_060M", f"> {r_t}")
    try:
        import terrain_illumination as ti
        if ti.available():
            dark = {k: ti.sample_pct(ti._map("sun"), *v, half=1) for k, v in {"Shackleton": (-89.67, 129.78), "Haworth": (-86.9, 356.0), "Faustini": (-87.3, 77.0)}.items()}
            add("illumination", "Known permanently shadowed craters read ~0% sunlight in the NASA map", judge(max(dark.values()) < 1.0),
                {k: round(v, 2) for k, v in dark.items()}, "AVGVISIB_85S_060M", "< 1 %", "confirms the map is being read with the right orientation")
    except Exception as exc:  # reference file unreadable: say so
        add("illumination", "Permanent-shadow sanity check", "SKIP", None, "AVGVISIB_85S_060M", detail=str(exc))


# ------------------------------------------------------------------------------------------------ ephemeris
def check_ephemeris() -> None:
    files = sorted(glob.glob(str(ROOT / "ephemeris_cache" / "*.npz")))
    if not files:
        add("ephemeris", "Sun / Earth elevation vs JPL Horizons", "SKIP", None, "JPL Horizons", detail="ephemeris_cache is empty")
        return
    t = np.arange(es.N_SAMPLES, dtype=float)
    se, ee = [], []
    for f in files:
        z = np.load(f)
        la, lo = float(z["lat"]), float(z["lon"])
        se.append(np.sqrt(np.mean((es.sun_model(la, lo, t) - z["sun_el"]) ** 2)))
        ee.append(np.sqrt(np.mean((es.earth_model(la, lo, t) - z["earth_el"]) ** 2)))
    n = len(files)
    add("ephemeris", f"Sun elevation: RMSE of the analytic model vs real JPL Horizons ({n} sites x 1441 h)", judge(np.mean(se) < THRESHOLDS["horizons_sun_rmse_deg"]),
        round(float(np.mean(se)), 4), "JPL Horizons (body 10 from 301)", f"< {THRESHOLDS['horizons_sun_rmse_deg']} deg", f"worst site {np.max(se):.3f} deg")
    add("ephemeris", f"Earth elevation: RMSE of the analytic model vs real JPL Horizons ({n} sites x 1441 h)", judge(np.mean(ee) < THRESHOLDS["horizons_earth_rmse_deg"]),
        round(float(np.mean(ee)), 4), "JPL Horizons (body 399 from 301)", f"< {THRESHOLDS['horizons_earth_rmse_deg']} deg", f"worst site {np.max(ee):.3f} deg")


# ------------------------------------------------------------------------------------------------ constants & geometry
def check_constants_and_geometry() -> None:
    for name, (ours, ref, tol) in NASA_CONSTANTS.items():
        add("constants", f"{name}", judge(abs(ours - ref) <= tol), ours, f"NASA fact sheet / SORCE: {ref}", f"within {tol}")
    # mast horizon: exact dip from the model vs an independent tangent-line derivation, for every supported height
    worst = 0.0
    for h in (1, 5, 20, 50, 100, 150):
        d_tangent = math.sqrt(2 * ms.R_MOON_M * h + h * h)             # distance to the tangent point
        dip_independent = math.degrees(math.atan(d_tangent / ms.R_MOON_M))  # angle subtended at the Moon's centre = horizon dip
        worst = max(worst, abs(ms.tower_boost_deg(h) - dip_independent))
    add("geometry", "Mast horizon dip equals the independent tangent-line geometry (1-150 m)", judge(worst < THRESHOLDS["dip_formula_deg"]),
        f"{worst:.2e} deg", "sqrt(2Rh + h^2) / R", f"< {THRESHOLDS['dip_formula_deg']} deg")
    approx = math.degrees(math.sqrt(2 * 150 / ms.R_MOON_M))
    add("geometry", "Dip at 150 m agrees with the small-angle approximation sqrt(2h/R) within 1%", judge(abs(ms.tower_boost_deg(150) - approx) / approx < 0.01),
        round(ms.tower_boost_deg(150), 5), f"sqrt(2h/R) = {approx:.5f} deg", "< 1 %")


# ------------------------------------------------------------------------------------------------ scoring & solar physics
def check_scoring_and_solar() -> None:
    sums = {m: abs(sum(ps.mode_weights(m)) - 1.0) for m in ps.PRIORITY_MODES}
    add("scoring", "Priority-mode weights (terrain, solar, comms) sum to 1 in every mode", judge(max(sums.values()) < THRESHOLDS["weights_sum"]), {m: sum(ps.mode_weights(m)) for m in sums}, "definition", "= 1")
    r = ms._ranked()
    worst = 0.0
    for mode in ps.PRIORITY_MODES:
        wt, ws, wc = ps.mode_weights(mode)
        manual = wt * r["Terrain_Score"] + ws * r["Solar_Score"] + wc * r["Comms_Score"]
        worst = max(worst, float((ms.mode_scores(r, mode) - manual).abs().max()))
    add("scoring", "Mode scores equal weighted terrain / solar / comms components (100 sites x 3 modes)", judge(worst < THRESHOLDS["mode_score_diff"]), f"{worst:.1e}", "definition", f"< {THRESHOLDS['mode_score_diff']}")
    in_range = bool(r["Suitability_Score"].between(0, 100).all())
    add("scoring", "All 100 suitability scores lie within 0-100", judge(in_range), [round(float(r['Suitability_Score'].min()), 2), round(float(r['Suitability_Score'].max()), 2)], "definition", "0-100")

    # energy conservation: electrical power can never exceed irradiance x efficiency x area
    bad, peak_ratio = 0, 0.0
    for sid in sites()["Site_ID"]:
        s = ms.Scenario(site_id=sid, panel_area_m2=10.0, panel_tilt_deg=90.0, tower_height_m=150.0, duration_hours=1440)
        e = ms.evaluate_scenario(s, include_timeline=True)
        p = np.array(e["timeline"]["power_watts"])
        bound = ms.SOLAR_CONSTANT_W_M2 * ms.PV_EFFICIENCY * 10.0
        peak_ratio = max(peak_ratio, float(p.max()) / bound)
        bad += int((p > bound + 1e-6).any())
        if abs(e["timeline"]["cumulative_energy_kwh"][-1] - p.sum() / 1000.0) > 1e-3:
            bad += 1
    add("solar", "Power never exceeds S x efficiency x area, and energy = sum of hourly power (100 sites, 150 m mast)", judge(bad == 0),
        {"sites_violating": bad, "peak_fraction_of_bound": round(peak_ratio, 4)}, "energy conservation", "0 violations")


def run_benchmark() -> dict:
    CHECKS.clear()
    for fn in (check_terrain, check_illumination, check_ephemeris, check_constants_and_geometry, check_scoring_and_solar):
        try:
            fn()
        except Exception as exc:  # one unreadable reference must not hide the other checks
            add("error", fn.__name__, "FAIL", None, "", detail=f"{type(exc).__name__}: {exc}")
    c = {k: sum(1 for x in CHECKS if x["status"] == k) for k in ("PASS", "FAIL", "INFO", "SKIP")}
    report = {"summary": {**c, "total": len(CHECKS), "strict_checks_passed": c["FAIL"] == 0 and c["PASS"] > 0},
              "thresholds": THRESHOLDS, "checks": list(CHECKS)}
    OUT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = run_benchmark()
    for x in rep["checks"]:
        print(f"[{x['status']:4s}] {x['group']:12s} {x['name']}  ->  {x['value']}  (ref: {x['reference']}; {x['threshold']}) {x['detail'][:90]}")
    s = rep["summary"]
    print(f"\n{s['PASS']} PASS · {s['FAIL']} FAIL · {s['INFO']} INFO · {s['SKIP']} SKIP  of {s['total']} checks")
    sys.exit(0 if s["FAIL"] == 0 else 1)
