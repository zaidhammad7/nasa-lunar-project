"""Live mission-planning inference for the lunar south pole.

    python src/analysis/predict_site.py --lat -85.3109 --lon 332.293
    python src/analysis/predict_site.py --lat -85.3109 --lon 332.293 --profile crewed_heavy --radius 5

`evaluate_new_coordinates(lat, lon, ...)` returns a JSON-serialisable dict (schema 2.0).
Schema 1.x keys (input, metrics, component_scores, Suitability_Score, Safety_Class,
class_probabilities, rule_based_check, justification, data_sources, warnings,
window_utc, model) are unchanged; new keys are additive:
  lander_profile, profile_assessment, explanation, confidence, hazard_flags,
  operations_telemetry, mission_readiness, mission_brief, landing_corridor (--radius).

Data stages degrade gracefully and report their source:
  Ephemeris : JPL Horizons API      -> fallback: inverse-distance interpolation of the CSV
  Terrain   : USGS LOLA 118 m DEM   -> fallback: inverse-distance interpolation of the CSV
Visibility = body elevation above the local flat horizon, hourly; "visible" = elevation > 0;
averages are over all samples (same convention as the training dataset).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ephemeris_series import (START_TIME, STEP, STEP_HOURS, STOP_TIME, get_hourly_series, load_terrain_cache,
                              save_terrain_cache,  # noqa: E402
                              series_stats)
from suitability import (ACCEPTABLE_MIN_SCORE, DATA_CSV, FEATURES, MODELS_DIR, OUTPUTS_DIR, SLOPE_IDEAL_DEG, SLOPE_LIMIT_DEG,  # noqa: E402
                         W_COMMS, W_SOLAR, W_TERRAIN, comms_score, safety_class, solar_score, terrain_score)

SCHEMA_VERSION = "2.1"
DEM_URL = "https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"
DEM_BASE_PIXEL_M = 118.4505876  # LDEM_118m pixel size at the equator (m)
DEM_SCALE_FALLBACK = 0.5  # LDEM_118m int16 DN -> metres, used only if the file has no scale tag
HTTP_TIMEOUT_S = 60
IDW_NEIGHBOURS = 4
FOOTPRINT_M = 120.0             # lander-footprint scale used to smooth slope when screening a corridor
_DEM_LOCK = threading.RLock()
_DEM_WARMING = False
_DEM_HANDLE = None            # (dataset, geodetic->proj, proj->geodetic); opening costs ~15 s, so cached

# ---- Lander profiles (ILLUSTRATIVE engineering envelopes - tune to your vehicle) ----
PROFILES = {
    "generic":       {"max_slope_deg": 15.0, "min_sun_pct": 50.0, "min_earth_pct": 40.0},
    "small_robotic": {"max_slope_deg": 10.0, "min_sun_pct": 40.0, "min_earth_pct": 30.0},
    "crewed_heavy":  {"max_slope_deg": 5.0,  "min_sun_pct": 65.0, "min_earth_pct": 50.0},
}
DEFAULT_PROFILE = "generic"
IDEAL_TO_LIMIT_RATIO = SLOPE_IDEAL_DEG / SLOPE_LIMIT_DEG  # "ideal" slope scales with the lander limit
MARGINAL_SLOPE_FRACTION = 0.8   # slope above 80% of the limit -> WARNING
LONG_DARK_HOURS = 100.0         # continuous Sun-below-horizon stretch flagged as survival-class darkness
LONG_BLACKOUT_HOURS = 150.0     # continuous Earth-below-horizon stretch flagged as comms blackout
SHORT_BASELINE_M = 20.0         # E-W slope baseline below this is noise-limited by DEM quantisation
POLAR_CAP_LAT = -89.0           # cos(lat) scaling is ill-conditioned poleward of this
CI_Z = 1.96                     # ~95% interval from cross-validated RMSE
FALLBACK_RMSE = 2.05            # used only if outputs/cv_metrics.json is missing
CORRIDOR_MAX_KM = 25.0
CORRIDOR_MIN_SEP_M = 300.0
RELOCATE_MIN_GAIN_PTS = 2.0     # don't recommend moving the target for less than this profile-score gain
MAX_WINDOW_PX = 3000


# ----------------------------------------------------------------------------
# Input handling
# ----------------------------------------------------------------------------
def _validate(lat: float, lon: float) -> tuple[float, float]:
    """Check range (south polar cap -90..-85 deg) and wrap lon to [0, 360)."""
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("lat/lon must be finite numbers")
    if not -90.0 <= lat <= -85.0:
        raise ValueError(f"lat={lat} outside supported range [-90, -85] deg (south polar cap)")
    return lat, lon % 360.0


def resolve_profile(profile: str | None = None, max_slope_deg: float | None = None,
                    min_sun_pct: float | None = None, min_earth_pct: float | None = None) -> dict:
    """Merge a named preset with explicit overrides into a lander-profile dict."""
    name = profile or DEFAULT_PROFILE
    if name not in PROFILES:
        raise ValueError(f"unknown profile '{name}'; choose from {sorted(PROFILES)}")
    p = dict(PROFILES[name])
    overridden = []
    for key, val in (("max_slope_deg", max_slope_deg), ("min_sun_pct", min_sun_pct), ("min_earth_pct", min_earth_pct)):
        if val is not None:
            p[key] = float(val)
            overridden.append(key)
    if not 0 <= p["max_slope_deg"] <= 45:
        raise ValueError("max_slope_deg must be in [0, 45]")
    for k in ("min_sun_pct", "min_earth_pct"):
        if not 0 <= p[k] <= 100:
            raise ValueError(f"{k} must be in [0, 100]")
    return {"name": name, **p, "overridden": overridden, "illustrative": True}


# ----------------------------------------------------------------------------
# Ephemeris (JPL Horizons)
# ----------------------------------------------------------------------------
def _longest_run_hours(mask: np.ndarray) -> float:
    """Longest consecutive run of True in a boolean series, in hours."""
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best * STEP_HOURS


def ephemeris_features(sun_el: np.ndarray, earth_el: np.ndarray) -> dict:
    """Dataset-style visibility features + longest continuous outages from hourly elevations."""
    out = series_stats(sun_el, earth_el)
    out["Sun_Longest_Dark_h"] = _longest_run_hours(sun_el <= 0)
    out["Sun_Longest_Lit_h"] = _longest_run_hours(sun_el > 0)
    out["Earth_Longest_Blackout_h"] = _longest_run_hours(earth_el <= 0)
    return out


def get_ephemeris_metrics(lat: float, lon: float) -> dict:
    """Sun/Earth visibility metrics from real Horizons data (cache first, live otherwise; raises on failure)."""
    s = get_hourly_series(lat, lon, mode="live")
    return ephemeris_features(s.sun_el, s.earth_el)


# ----------------------------------------------------------------------------
# Terrain (LOLA DEM)
# ----------------------------------------------------------------------------
def _dem():
    """Open the LOLA DEM once per process (the remote header read costs ~15 s) and cache the handle.

    Callers must hold _DEM_LOCK while using the dataset (GDAL handles are not thread-safe).
    """
    global _DEM_HANDLE
    with _DEM_LOCK:
        if _DEM_HANDLE is None:
            import rasterio
            from pyproj import Transformer
            os.environ.setdefault("GDAL_HTTP_TIMEOUT", str(HTTP_TIMEOUT_S))
            os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
            ds = rasterio.open(DEM_URL)
            if ds.crs is None:
                ds.close()
                raise RuntimeError("DEM has no CRS")
            _DEM_HANDLE = (ds, Transformer.from_crs(ds.crs.geodetic_crs, ds.crs, always_xy=True),
                           Transformer.from_crs(ds.crs, ds.crs.geodetic_crs, always_xy=True))
        return _DEM_HANDLE


def _dem_scale(ds) -> float:
    return ds.scales[0] if ds.scales and ds.scales[0] not in (None, 1.0) else DEM_SCALE_FALLBACK


def get_terrain_metrics(lat: float, lon: float) -> dict:
    """Elevation (m) and slope (deg) from the 118 m LOLA DEM (raises on any failure).

    Reads only a 3x3 window over HTTP range requests. East-west pixel spacing is
    dx = base_pixel_m * cos(lat); north-south spacing dy = base_pixel_m (118.45 m).
    Central differences - verified to reproduce Slope_deg in the dataset.
    """
    from rasterio.windows import Window

    with _DEM_LOCK:
        ds, to_proj, _ = _dem()
        lon_f = lon if ds.bounds.left >= 0 else (lon + 180.0) % 360.0 - 180.0
        x, y = to_proj.transform(lon_f, lat)
        row, col = ds.index(x, y)
        z = ds.read(1, window=Window(col - 1, row - 1, 3, 3), boundless=True,
                    fill_value=ds.nodata or 0).astype(float)
        z = z * _dem_scale(ds) + (ds.offsets[0] if ds.offsets and ds.offsets[0] else 0.0)
        base_pixel = float(ds.res[0])
    dx = base_pixel * math.cos(math.radians(lat))
    dzdx = (z[1, 2] - z[1, 0]) / (2 * dx)
    dzdy = (z[2, 1] - z[0, 1]) / (2 * base_pixel)
    return {"Elevation_m": float(z[1, 1]), "Slope_deg": float(math.degrees(math.atan(math.hypot(dzdx, dzdy)))),
            "Roughness_m": plane_detrended_roughness(z, dx, base_pixel), "_dx_m": dx}


def plane_detrended_roughness(z: np.ndarray, dx_m: float, dy_m: float) -> float:
    """Std-dev (m) of the residual of a 3x3 elevation window after removing its best-fit plane.

    The plane z = a*x + b*y + c is fitted by least squares on metric coordinates
    (x east = col * dx, y north = -row * dy); Roughness_m = population std of the residuals.
    """
    rows, cols = np.mgrid[-1:2, -1:2]
    A = np.column_stack([(cols * dx_m).ravel(), (-rows * dy_m).ravel(), np.ones(9)])
    coef, *_ = np.linalg.lstsq(A, z.ravel(), rcond=None)
    return float(np.std(z.ravel() - A @ coef))


DEM_WARM_POINT = (-88.3448, 225.8806)  # (lat, lon) read at start-up so GDAL's HTTP + TIFF-header caches are hot
_DEM_HOT = False
_DEM_ERROR: str | None = None


def dem_ready() -> bool:
    """True once the remote DEM is open AND a warm-up 3x3 read has succeeded (reads are then ~1 s or less)."""
    return _DEM_HOT


def dem_error() -> str | None:
    """Last DEM warm-up failure message (None if none)."""
    return _DEM_ERROR


def warm_dem() -> dict:
    """Open the LOLA DEM and read a 3x3 window at DEM_WARM_POINT (blocking, idempotent). Returns timings in ms."""
    global _DEM_HOT, _DEM_ERROR
    t0 = time.perf_counter()
    try:
        _dem()
        t1 = time.perf_counter()
        t = get_terrain_metrics(*DEM_WARM_POINT)
        t2 = time.perf_counter()
        _DEM_HOT, _DEM_ERROR = True, None
    except Exception as exc:
        _DEM_ERROR = f"{type(exc).__name__}: {str(exc)[:160]}"
        raise
    return {"open_ms": round((t1 - t0) * 1000, 1), "read_ms": round((t2 - t1) * 1000, 1),
            "warm_point": {"lat_deg": DEM_WARM_POINT[0], "lon_deg_east": DEM_WARM_POINT[1]},
            "elevation_m": t["Elevation_m"], "slope_deg": round(t["Slope_deg"], 3)}


def warm_dem_async() -> None:
    """Warm the DEM in a background thread (idempotent); first open costs ~15 s."""
    global _DEM_WARMING
    if dem_ready() or _DEM_WARMING:
        return
    _DEM_WARMING = True

    def _run():
        global _DEM_WARMING
        try:
            warm_dem()
        except Exception:
            pass
        finally:
            _DEM_WARMING = False

    threading.Thread(target=_run, name="dem-warm", daemon=True).start()


def get_terrain_metrics_fast(lat: float, lon: float) -> dict:
    """Terrain for a custom point without ever blocking on the slow first DEM open.

    Order: on-disk terrain cache -> hot DEM read (result is then cached) -> TimeoutError
    (after starting a background warm-up) so callers can fall back to CSV interpolation.
    """
    cached = load_terrain_cache(lat, lon)
    if cached is not None:
        return {**cached, "_from_cache": True}
    if _DEM_HANDLE is None:
        warm_dem_async()
        raise TimeoutError("DEM is still opening in the background; retry in ~15 s")
    t = get_terrain_metrics(lat, lon)
    save_terrain_cache(lat, lon, t)
    return t


# ----------------------------------------------------------------------------
# Landing corridor: neighbourhood scan around the target
# ----------------------------------------------------------------------------
def scan_neighbourhood(lat: float, lon: float, radius_km: float, max_slope_deg: float, k: int = 3) -> dict:
    """Scan every DEM cell within `radius_km` and pick k low-slope, well-separated candidates.

    Per-cell slope uses the same central-difference definition as the dataset, then is
    averaged over a ~FOOTPRINT_M window (a lander footprint) to suppress single-pixel
    quantisation noise before candidates are ranked.
    """
    import rasterio
    from scipy.ndimage import uniform_filter

    with _DEM_LOCK:
        ds, to_proj, to_geo = _dem()
        lon_f = lon if ds.bounds.left >= 0 else (lon + 180.0) % 360.0 - 180.0
        x, y = to_proj.transform(lon_f, lat)
        row, col = ds.index(x, y)
        base = float(ds.res[0])
        dx, dy = base * math.cos(math.radians(lat)), base
        hr = min(math.ceil(radius_km * 1000 / dy), MAX_WINDOW_PX)
        hc = min(math.ceil(radius_km * 1000 / dx), MAX_WINDOW_PX)
        win = rasterio.windows.Window(col - hc - 1, row - hr - 1, 2 * hc + 3, 2 * hr + 3)
        raw = ds.read(1, window=win, boundless=True, fill_value=ds.nodata)
        nodata, scale = ds.nodata, _dem_scale(ds)

        valid_all = raw != nodata if nodata is not None else np.ones(raw.shape, bool)
        z = raw.astype(float) * scale
        gx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * dx)
        gy = (z[2:, 1:-1] - z[:-2, 1:-1]) / (2 * dy)
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        valid = valid_all[1:-1, 2:] & valid_all[1:-1, :-2] & valid_all[2:, 1:-1] & valid_all[:-2, 1:-1]
        n_cols = max(1, round(FOOTPRINT_M / dx))
        smooth = uniform_filter(np.where(valid, slope, np.nan_to_num(np.nanmean(np.where(valid, slope, np.nan)))),
                                size=(1, n_cols), mode="nearest")
        ii, jj = np.mgrid[-hr:hr + 1, -hc:hc + 1]
        north_m, east_m = -ii * dy, jj * dx
        dist = np.hypot(north_m, east_m)
        mask = valid & (dist <= radius_km * 1000)
        if not mask.any():
            raise RuntimeError("no valid DEM cells in the scan window")
        flat_idx = np.flatnonzero(mask)
        sm_flat, d_flat = smooth.ravel(), dist.ravel()
        order = flat_idx[np.lexsort((d_flat[flat_idx], np.round(sm_flat[flat_idx], 1)))]
        n_flat, e_flat = north_m.ravel(), east_m.ravel()
        picks: list[int] = []
        for idx in order:
            if all(math.hypot(n_flat[idx] - n_flat[p], e_flat[idx] - e_flat[p]) >= CORRIDOR_MIN_SEP_M for p in picks):
                picks.append(int(idx))
            if len(picks) >= k:
                break
        cands = []
        for idx in picks:
            cx, cy = ds.xy(row + int(ii.ravel()[idx]), col + int(jj.ravel()[idx]))
            clon, clat = to_geo.transform(cx, cy)
            nm, em = float(n_flat[idx]), float(e_flat[idx])
            cands.append({"lat_deg": float(clat), "lon_deg_east": float(clon % 360.0),
                          "distance_m": round(math.hypot(nm, em), 1),
                          "bearing_deg": round(math.degrees(math.atan2(em, nm)) % 360.0, 1),
                          "footprint_slope_deg": round(float(sm_flat[idx]), 3)})
        sl = smooth[mask]
        return {"candidates": cands, "cells_scanned": int(mask.sum()), "footprint_m": FOOTPRINT_M,
                "footprint_slope_stats_deg": {"min": round(float(sl.min()), 2), "median": round(float(np.median(sl)), 2),
                                              "p90": round(float(np.percentile(sl, 90)), 2),
                                              "max": round(float(sl.max()), 2)},
                "pct_cells_within_slope_limit": round(float((sl <= max_slope_deg).mean() * 100), 1)}


# ----------------------------------------------------------------------------
# Offline fallback: inverse-distance interpolation over the 100-site CSV
# ----------------------------------------------------------------------------
def _polar_xy(lat, lon):
    r = 90.0 + np.asarray(lat, dtype=float)
    t = np.deg2rad(lon)
    return np.stack([r * np.cos(t), r * np.sin(t)], axis=-1)


def interpolate_from_dataset(lat: float, lon: float, columns: list[str]) -> dict:
    """IDW over the nearest IDW_NEIGHBOURS sites in polar-plane distance (approximate)."""
    df = _dataset()
    d = np.linalg.norm(_polar_xy(df["Lat"], df["Lon"]) - _polar_xy(lat, lon), axis=1)
    idx = np.argsort(d)[:IDW_NEIGHBOURS]
    w = 1.0 / np.maximum(d[idx], 1e-6)
    return {c: float(np.average(df[c].to_numpy()[idx], weights=w)) for c in columns}


# ----------------------------------------------------------------------------
# Cached resources
# ----------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _dataset() -> pd.DataFrame:
    return pd.read_csv(DATA_CSV)


@lru_cache(maxsize=1)
def _load_models():
    reg = joblib.load(MODELS_DIR / "best_regressor.joblib")
    clf = joblib.load(MODELS_DIR / "best_classifier.joblib")
    return reg, clf


@lru_cache(maxsize=1)
def _cv_rmse() -> tuple[float, str]:
    """Cross-validated RMSE of the deployed regressor (points) and where it came from."""
    try:
        reg, _ = _load_models()
        m = json.loads((OUTPUTS_DIR / "cv_metrics.json").read_text())
        return float(m["regressors"][reg["name"]]["RMSE_mean"]), "5-fold CV RMSE (outputs/cv_metrics.json)"
    except Exception:
        return FALLBACK_RMSE, "default CV RMSE (cv_metrics.json missing)"


# ----------------------------------------------------------------------------
# Data collection / prediction
# ----------------------------------------------------------------------------
def _collect(lat: float, lon: float, allow_offline_fallback: bool, force_offline: bool) -> dict:
    """Gather physical features from live sources, falling back to the CSV if allowed."""
    sources, warnings, metrics = {}, [], {}
    ephem_cols = [f for f in FEATURES if f.startswith(("Sun", "Earth"))]
    try:
        if force_offline:
            raise RuntimeError("offline mode requested")
        metrics.update(get_ephemeris_metrics(lat, lon))
        sources["ephemeris"] = "JPL Horizons API"
    except Exception as exc:
        if not (allow_offline_fallback or force_offline):
            raise
        metrics.update(interpolate_from_dataset(lat, lon, ephem_cols))
        sources["ephemeris"] = "dataset IDW interpolation (offline fallback)"
        warnings.append(f"Horizons unavailable ({type(exc).__name__}: {str(exc)[:120]}).")
    try:
        if force_offline:
            raise RuntimeError("offline mode requested")
        metrics.update(get_terrain_metrics(lat, lon))
        sources["terrain"] = "USGS LOLA 118 m DEM"
    except Exception as exc:
        if not (allow_offline_fallback or force_offline):
            raise
        metrics.update(interpolate_from_dataset(lat, lon, ["Elevation_m", "Slope_deg"]))
        sources["terrain"] = "dataset IDW interpolation (offline fallback)"
        warnings.append(f"LOLA DEM unavailable ({type(exc).__name__}: {str(exc)[:120]}).")
    return {"metrics": metrics, "sources": sources, "warnings": warnings}


def _tree_values(forest, X: np.ndarray) -> np.ndarray:
    """Raw per-tree outputs (n_trees, n_rows, n_outputs) via the C trees, skipping sklearn's per-call validation."""
    v = np.ascontiguousarray(X, dtype=np.float32)
    return np.stack([np.asarray(e.tree_.predict(v)).reshape(v.shape[0], -1) for e in forest.estimators_])


def fast_forest_proba(clf, X: np.ndarray) -> np.ndarray:
    """RandomForestClassifier.predict_proba for a few rows, ~10x faster than sklearn's wrapper."""
    vals = _tree_values(clf, X)
    vals = vals / np.clip(vals.sum(axis=2, keepdims=True), 1e-12, None)
    return vals.mean(axis=0)


def _predict(metrics: dict) -> dict:
    """Run both joblib models on the feature dict."""
    reg, clf = _load_models()
    X = pd.DataFrame([[metrics[f] for f in FEATURES]], columns=FEATURES)
    score = float(np.clip(reg["model"].predict(X)[0], 0, 100))
    proba = fast_forest_proba(clf["model"], X.to_numpy())[0]
    ml_class = str(clf["model"].classes_[int(np.argmax(proba))])
    return {"X": X, "score": score, "classes": [str(c) for c in clf["model"].classes_], "proba": proba,
            "ml_class": ml_class, "reg": reg, "clf": clf}


def _components(m: dict, profile: dict | None = None) -> dict:
    """Sub-scores (0-100); terrain uses the profile's slope limits if given."""
    limit = max(profile["max_slope_deg"], 0.1) if profile else SLOPE_LIMIT_DEG
    ideal = limit * IDEAL_TO_LIMIT_RATIO if profile else SLOPE_IDEAL_DEG
    return {"terrain": float(terrain_score(m["Slope_deg"], ideal, limit)),
            "solar": float(solar_score(m["Sun_Visible_Pct"], m["Sun_Max_El"])),
            "comms": float(comms_score(m["Earth_Visible_Pct"], m["Earth_Avg_El"]))}, ideal, limit


# ----------------------------------------------------------------------------
# Explanation, confidence, hazards, readiness
# ----------------------------------------------------------------------------
def explain(m: dict, pred: dict, score_default_profile: dict) -> dict:
    """Weighted score decomposition + local one-at-a-time sensitivity of the ML score."""
    comp = score_default_profile
    weights = {"terrain": W_TERRAIN, "solar": W_SOLAR, "comms": W_COMMS}
    contrib = {k: round(weights[k] * comp[k], 2) for k in comp}
    lost = {k: round(weights[k] * (100 - comp[k]), 2) for k in comp}
    median = _dataset()[FEATURES].median()
    X2 = pd.concat([pred["X"]] * len(FEATURES), ignore_index=True)
    for i, f in enumerate(FEATURES):
        X2.loc[i, f] = median[f]
    occluded = np.clip(pred["reg"]["model"].predict(X2), 0, 100)  # one batched call
    attrib = {f: float(pred["score"] - occluded[i]) for i, f in enumerate(FEATURES)}
    ordered = dict(sorted(((k, round(v, 2)) for k, v in attrib.items()), key=lambda kv: -abs(kv[1])))
    return {
        "weights": {k: v for k, v in weights.items()},
        "weighted_contributions_pts": contrib,
        "points_lost_by_component": lost,
        "limiting_factor": max(lost, key=lost.get),
        "feature_sensitivity_pts": ordered,
        "sensitivity_method": ("ML score minus ML score with that feature replaced by the dataset median "
                               "(one-at-a-time occlusion; positive = feature raises this site's score)"),
    }


def confidence(m: dict, pred: dict, sources: dict, rule_class: str, safety: str) -> dict:
    """Prediction interval, class confidence, out-of-distribution check and a coarse level."""
    rmse, basis = _cv_rmse()
    score = pred["score"]
    ds = _dataset()
    ood = [f for f in FEATURES if not ds[f].min() <= m[f] <= ds[f].max()]
    class_conf = float(pred["proba"].max())
    live = all(("offline" not in v) and ("fallback" not in v) for v in sources.values())
    agree = pred["ml_class"] == rule_class
    if live and not ood and class_conf >= 0.8 and agree:
        level = "HIGH"
    elif class_conf >= 0.6 and len(ood) <= 1:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {"level": level,
            "score_interval_95": [round(max(0.0, score - CI_Z * rmse), 2), round(min(100.0, score + CI_Z * rmse), 2)],
            "interval_basis": f"+/-{CI_Z} x {rmse:.2f} pts ({basis}); assumes homoscedastic errors",
            "class_confidence": round(class_conf, 3), "ml_rule_agreement": bool(agree),
            "out_of_distribution_features": ood, "live_data": bool(live)}


def _flag(code: str, severity: str, message: str, value=None, threshold=None) -> dict:
    return {"code": code, "severity": severity, "message": message,
            "value": None if value is None else round(float(value), 2),
            "threshold": None if threshold is None else round(float(threshold), 2)}


def hazard_flags(m: dict, tele: dict, profile: dict, sources: dict, conf: dict, lat: float) -> list[dict]:
    """Structured hazards against the lander profile (severity: CRITICAL > WARNING > INFO)."""
    lim, flags = profile["max_slope_deg"], []
    s = m["Slope_deg"]
    if s > lim:
        flags.append(_flag("SLOPE_EXCEEDS_LIMIT", "CRITICAL",
                           f"Slope {s:.1f} deg exceeds the {lim:.0f} deg {profile['name']} tip-over limit.", s, lim))
    elif s > MARGINAL_SLOPE_FRACTION * lim:
        flags.append(_flag("SLOPE_MARGINAL", "WARNING",
                           f"Slope {s:.1f} deg uses >{MARGINAL_SLOPE_FRACTION:.0%} of the {lim:.0f} deg limit.", s, lim))
    if m["Sun_Visible_Pct"] < profile["min_sun_pct"]:
        flags.append(_flag("LOW_SUN_AVAILABILITY", "WARNING",
                           f"Sun visible {m['Sun_Visible_Pct']:.0f}% < required {profile['min_sun_pct']:.0f}%.",
                           m["Sun_Visible_Pct"], profile["min_sun_pct"]))
    if m["Earth_Visible_Pct"] < profile["min_earth_pct"]:
        flags.append(_flag("LOW_EARTH_LINK", "WARNING",
                           f"Earth visible {m['Earth_Visible_Pct']:.0f}% < required {profile['min_earth_pct']:.0f}%.",
                           m["Earth_Visible_Pct"], profile["min_earth_pct"]))
    dark = tele.get("sun_longest_dark_h")
    if dark is not None and dark > LONG_DARK_HOURS:
        flags.append(_flag("LONG_DARKNESS", "WARNING",
                           f"Longest continuous Sun outage {dark:.0f} h - size batteries/thermal for survival.",
                           dark, LONG_DARK_HOURS))
    blk = tele.get("earth_longest_blackout_h")
    if blk is not None and blk > LONG_BLACKOUT_HOURS:
        flags.append(_flag("LONG_COMMS_BLACKOUT", "INFO",
                           f"Longest continuous Earth outage {blk:.0f} h - plan autonomy / store-and-forward.",
                           blk, LONG_BLACKOUT_HOURS))
    if tele.get("slope_baseline_ew_m") is not None and tele["slope_baseline_ew_m"] < SHORT_BASELINE_M:
        flags.append(_flag("SLOPE_NOISE_LIMITED", "INFO",
                           f"E-W slope baseline only {tele['slope_baseline_ew_m']:.0f} m at this latitude; "
                           "slope is sensitive to DEM quantisation (0.5 m).", tele["slope_baseline_ew_m"], SHORT_BASELINE_M))
    if lat < POLAR_CAP_LAT:
        flags.append(_flag("POLAR_PROJECTION_DISTORTION", "WARNING",
                           f"Latitude {lat:.2f} deg is within 1 deg of the pole: cos(lat) scaling of the equirectangular "
                           "DEM is ill-conditioned; verify with a polar-stereographic DEM.", lat, POLAR_CAP_LAT))
    if any(("offline" in v) or ("fallback" in v) for v in sources.values()):
        flags.append(_flag("FALLBACK_DATA", "WARNING",
                           "One or more inputs were interpolated from the 100-site CSV, not measured live."))
    if conf["out_of_distribution_features"]:
        flags.append(_flag("OUT_OF_DISTRIBUTION", "WARNING",
                           "Features outside the training range: " + ", ".join(conf["out_of_distribution_features"]) + "."))
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    return sorted(flags, key=lambda f: order[f["severity"]])


def readiness(flags: list[dict]) -> str:
    """NO-GO if any CRITICAL flag, CAUTION if any WARNING, else GO."""
    sev = {f["severity"] for f in flags}
    return "NO-GO" if "CRITICAL" in sev else "CAUTION" if "WARNING" in sev else "GO"


def engineering_justification(m: dict, safety: str) -> list[str]:
    """Plain-language reasons tied to the physical metrics (schema 1.x contract)."""
    s, notes = m["Slope_deg"], []
    if s <= 5:
        notes.append(f"Terrain: slope {s:.1f} deg is within the ideal <=5 deg envelope for touchdown stability.")
    elif s <= 15:
        notes.append(f"Terrain: slope {s:.1f} deg is acceptable (<=15 deg) but erodes tip-over margin.")
    else:
        notes.append(f"Terrain: slope {s:.1f} deg exceeds the 15 deg lander tip-over limit.")
    sv = m["Sun_Visible_Pct"]
    notes.append(f"Power/thermal: Sun above horizon {sv:.0f}% of the window (max elevation {m['Sun_Max_El']:.1f} deg) - "
                 + ("strong solar availability." if sv >= 65 else "moderate; battery/RHU sizing needed for long eclipses."
                    if sv >= 50 else "poor; long-duration darkness expected."))
    ev = m["Earth_Visible_Pct"]
    notes.append(f"Comms: Earth visible {ev:.0f}% of the window (mean elevation {m['Earth_Avg_El']:.1f} deg) - "
                 + ("good direct-to-Earth link." if ev >= 50 else "intermittent link; plan a relay or store-and-forward."))
    notes.append(f"Overall classification: {safety}.")
    return notes


def _bearing_name(deg: float) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((deg + 22.5) % 360) // 45)]


# ----------------------------------------------------------------------------
# Corridor evaluation
# ----------------------------------------------------------------------------
def _summarise(res: dict, extra: dict | None = None) -> dict:
    """Compact per-site summary used for corridor candidates."""
    out = {"lat_deg": res["input"]["lat_deg"], "lon_deg_east": res["input"]["lon_deg_east"],
           "slope_deg": res["metrics"]["Slope_deg"], "Sun_Visible_Pct": res["metrics"]["Sun_Visible_Pct"],
           "Earth_Visible_Pct": res["metrics"]["Earth_Visible_Pct"],
           "Suitability_Score": res["Suitability_Score"], "Safety_Class": res["Safety_Class"],
           "profile_score": res["profile_assessment"]["rule_based_score"],
           "mission_readiness": res["mission_readiness"], "n_hazard_flags": len(res["hazard_flags"]),
           "data_sources": res["data_sources"]}
    return {**(extra or {}), **out}


def landing_corridor(lat: float, lon: float, target: dict, profile: dict, radius_km: float, k: int,
                     allow_offline_fallback: bool, force_offline: bool) -> dict:
    """Scan radius_km around the target and recommend the best nearby touchdown point."""
    if not 0 < radius_km <= CORRIDOR_MAX_KM:
        raise ValueError(f"radius_km must be in (0, {CORRIDOR_MAX_KM}]")
    base = {"radius_km": radius_km, "status": "ok"}
    if force_offline:
        return {**base, "status": "unavailable", "reason": "offline mode: DEM scan needs the live LOLA DEM"}
    try:
        scan = scan_neighbourhood(lat, lon, radius_km, profile["max_slope_deg"], k)
    except Exception as exc:
        return {**base, "status": "unavailable", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}

    pts = [c for c in scan.pop("candidates") if -90.0 <= c["lat_deg"] <= -85.0]
    scan_info = scan

    evaluated = []
    for c in pts:  # sequential: Horizons rejects concurrent requests
        r = evaluate_new_coordinates(c["lat_deg"], c["lon_deg_east"], allow_offline_fallback,
                                     profile=profile["name"], max_slope_deg=profile["max_slope_deg"],
                                     min_sun_pct=profile["min_sun_pct"], min_earth_pct=profile["min_earth_pct"],
                                     explain_result=False)
        evaluated.append(_summarise(r, {k_: c[k_] for k_ in ("distance_m", "bearing_deg", "footprint_slope_deg")}))
    tgt = _summarise(target, {"distance_m": 0.0, "bearing_deg": None})
    pool_ = [tgt] + evaluated
    ok = [c for c in pool_ if c["slope_deg"] <= profile["max_slope_deg"]] or pool_
    best = max(ok, key=lambda c: (c["profile_score"], -c["distance_m"]))
    gain = round(best["profile_score"] - tgt["profile_score"], 2)
    hold = best is tgt or gain < RELOCATE_MIN_GAIN_PTS
    return {**base, **scan_info, "target": tgt, "candidates": evaluated,
            "recommended": tgt if hold else best,
            "recommended_action": "HOLD_TARGET" if hold else "RELOCATE",
            "profile_score_gain_vs_target": 0.0 if hold else gain,
            "ranking_basis": (f"highest profile_score among sites meeting the slope limit; relocate only if the gain "
                              f"is >= {RELOCATE_MIN_GAIN_PTS:g} pts"),
            "note": ("Candidates are screened on dataset-style slope averaged over a ~120 m footprint, then fully "
                     "re-evaluated (slope, Sun, Earth) with the standard pipeline. Boulders and craters smaller than "
                     "the 118 m DEM posting are not resolved.")}


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Hybrid physics + ML: guardrails, uncertainty, batch inference
# ----------------------------------------------------------------------------
GUARDRAILS = (
    # code, feature, test, cap, message
    ("TIP_OVER", "Slope_deg", lambda v: v > 15.0, 35.0, "CRITICAL: Terrain slope exceeds 15° lander tip-over limit."),
    ("PSR", "Sun_Visible_Pct", lambda v: v < 25.0, 30.0,
     "CRITICAL: Permanently Shadowed Region (PSR) risk — prolonged crater shadowing and extreme cryogenic hazard."),
    ("DTE_BLACKOUT", "Earth_Visible_Pct", lambda v: v < 10.0, 35.0, "CRITICAL: Severe Direct-to-Earth (DTE) communication blackout."),
)
STATUS_LABELS = {"Optimal": "GO / Optimal", "Acceptable": "CONDITIONAL / Acceptable", "Hazardous": "NO-GO / Hazardous"}
UNCERTAINTY_MODEL_FILE = "uncertainty_ensemble.joblib"


@lru_cache(maxsize=1)
def _uncertainty_model():
    """Random-forest ensemble used for per-tree score spread (None if not trained yet)."""
    try:
        return joblib.load(MODELS_DIR / UNCERTAINTY_MODEL_FILE)["model"]
    except Exception:
        return None


def ensemble_std(X: pd.DataFrame) -> np.ndarray:
    """Per-row std (score points) of the individual trees' predictions (running sums, low memory)."""
    rf = _uncertainty_model()
    if rf is None:
        return np.full(len(X), np.nan)
    v = np.ascontiguousarray(X[FEATURES].to_numpy(dtype=np.float32))
    s, s2 = np.zeros(len(v)), np.zeros(len(v))
    for e in rf.estimators_:
        p = np.asarray(e.tree_.predict(v)).reshape(len(v), -1)[:, 0].astype(float)
        s += p
        s2 += p * p
    n = len(rf.estimators_)
    return np.sqrt(np.maximum(s2 / n - (s / n) ** 2, 0.0))


def ci_half_width(X: pd.DataFrame) -> np.ndarray:
    """95% half-width (score points): 1.96 x tree std, or 1.96 x CV RMSE if the ensemble is unavailable."""
    std = ensemble_std(X)
    if np.isnan(std).any():
        return np.full(len(X), CI_Z * _cv_rmse()[0])
    return CI_Z * std


def apply_guardrails(df: pd.DataFrame, score: np.ndarray, cls: np.ndarray):
    """Vectorised hard physics shield. Returns (score, class, {code: bool mask})."""
    score, cls = np.asarray(score, dtype=float).copy(), np.asarray(cls, dtype=object).copy()
    masks = {}
    for code, feat, test, cap, _ in GUARDRAILS:
        m = test(df[feat].to_numpy(dtype=float))
        masks[code] = m
        score = np.where(m, np.minimum(score, cap), score)
        cls = np.where(m, "Hazardous", cls)
    return score, cls, masks


# ---- 3-layer aerospace safety factor (margin of safety + risk-averse asymmetric thresholds) ----
SAFETY_FACTOR_ACTIVE = True
SLOPE_SAFETY_MARGIN_DEG = 1.5      # operational slope limit = max_slope - margin (FS ~ 15/13.5 = 1.11)
ROUGHNESS_SLOPE_WEIGHT = 0.5       # slope + 0.5 * roughness_m must also stay within the mechanical limit
SCORE_SAFETY_BUFFER = 3.0          # Acceptable needs score >= 45 + 3 = 48 ...
# ... and the lower 95% bound (score - CI half-width) must stay >= 45
HAZARD_PROB_THRESHOLD = 0.28       # classifier override: P(Hazardous) >= 0.28 -> Hazardous (argmax would need ~0.5)
SAFETY_CAP_SCORE = ACCEPTABLE_MIN_SCORE - 1.0  # a Hazardous verdict never displays an Acceptable-looking score
SAFETY_LAYERS = ("SLOPE_DERATING", "SCORE_BUFFER", "HAZARD_PROB")


def effective_max_slope(max_slope_deg: float) -> float:
    """Derated operational slope limit (deg) = max_slope - 1.5 (never below 0)."""
    return max(0.0, float(max_slope_deg) - SLOPE_SAFETY_MARGIN_DEG)


def apply_safety_factor(df: pd.DataFrame, score, cls, p_haz, half_width, max_slope_deg=15.0, roughness=None):
    """Vectorised 3-layer safety factor applied after the hard guardrails.

    L1 SLOPE_DERATING: Slope > max_slope - 1.5, or Slope + 0.5*Roughness_m > max_slope.
    L2 SCORE_BUFFER  : score < 45 + 3 or lower 95% bound (score - half_width) < 45.
    L3 HAZARD_PROB   : classifier P(Hazardous) >= 0.28.
    Any layer forces Hazardous; every Hazardous verdict is capped at 44 (below the 45 Acceptable cutoff).
    Returns (score, class, {layer: bool mask}).
    """
    score, cls = np.asarray(score, dtype=float).copy(), np.asarray(cls, dtype=object).copy()
    slope = df["Slope_deg"].to_numpy(dtype=float)
    rough = np.zeros(len(df)) if roughness is None else np.nan_to_num(np.asarray(roughness, dtype=float))
    masks = {  # reported for every site, so telemetry shows which margins are violated even if ML already said Hazardous
        "SLOPE_DERATING": (slope > effective_max_slope(max_slope_deg)) | (slope + ROUGHNESS_SLOPE_WEIGHT * rough > max_slope_deg),
        "SCORE_BUFFER": (score < ACCEPTABLE_MIN_SCORE + SCORE_SAFETY_BUFFER)
                        | (score - np.asarray(half_width, dtype=float) < ACCEPTABLE_MIN_SCORE),
        "HAZARD_PROB": np.asarray(p_haz, dtype=float) >= HAZARD_PROB_THRESHOLD,
    }
    hit = masks["SLOPE_DERATING"] | masks["SCORE_BUFFER"] | masks["HAZARD_PROB"]
    cls = np.where(hit, "Hazardous", cls)
    score = np.where(cls == "Hazardous", np.minimum(score, SAFETY_CAP_SCORE), score)  # Hazardous never looks Acceptable
    return score, cls, masks


def ood_mask(df: pd.DataFrame) -> np.ndarray:
    """True where any feature lies outside the [min, max] of final_lunar_dataset_fixed.csv."""
    ds = _dataset()
    bad = np.zeros(len(df), dtype=bool)
    for f in FEATURES:
        v = df[f].to_numpy(dtype=float)
        bad |= (v < ds[f].min()) | (v > ds[f].max())
    return bad


def predict_batch(df: pd.DataFrame, safety_factor: bool = True, max_slope_deg: float = 15.0) -> pd.DataFrame:
    """Batch ML inference + guardrails (+ 3-layer safety factor) for many candidate sites.

    Input needs the FEATURES columns (optional Roughness_m, m). Output columns: score_raw, class_raw,
    confidence_pct, p_hazardous, half_width, Suitability_Score, Safety_Class, guard_<CODE>,
    safety_<LAYER>, ood. `safety_factor=False` reproduces the pre-safety-factor behaviour.
    """
    reg, clf = _load_models()
    X = df[FEATURES]
    score_raw = np.clip(reg["model"].predict(X), 0, 100)
    proba = clf["model"].predict_proba(X)
    classes = [str(c) for c in clf["model"].classes_]
    class_raw = np.asarray(classes)[np.argmax(proba, axis=1)]
    p_haz = proba[:, classes.index("Hazardous")]
    score, cls, masks = apply_guardrails(df, score_raw, class_raw)
    half = ci_half_width(X)
    out = pd.DataFrame({"score_raw": score_raw, "class_raw": class_raw, "confidence_pct": proba.max(axis=1) * 100,
                        "p_hazardous": p_haz, "half_width": half}, index=df.index)
    if safety_factor:
        rough = df["Roughness_m"].to_numpy() if "Roughness_m" in df.columns else None
        score, cls, sf = apply_safety_factor(df, score, cls, p_haz, half, max_slope_deg, rough)
        for layer, m in sf.items():
            out[f"safety_{layer}"] = m
    out["Suitability_Score"], out["Safety_Class"], out["ood"] = score, cls, ood_mask(df)
    for code, m in masks.items():
        out[f"guard_{code}"] = m
    return out


def score_interval(pred_score: float, std_pts: float, cap: float | None) -> dict:
    """95% interval (+/-1.96 x tree-ensemble std) on the (possibly capped) score."""
    if not math.isfinite(std_pts):
        rmse, basis = _cv_rmse()
        half, method = CI_Z * rmse, f"fallback: {basis}"
    else:
        half, method = CI_Z * std_pts, "95% CI = +/-1.96 x std of 300 random-forest tree predictions"
    hi = min(100.0, pred_score + half)
    if cap is not None:
        hi = min(hi, cap)
    return {"lower": round(max(0.0, pred_score - half), 2), "upper": round(hi, 2),
            "plus_minus": round(half, 2), "method": method}


def assess_features(lat: float, lon: float, raw: dict, sources: dict, warnings: list[str], prof: dict,
                    explain_result: bool = True) -> dict:
    """Score one site from already-collected physical features (no network).

    `raw` holds the FEATURES (plus optional Sun_Longest_Dark_h, Sun_Longest_Lit_h,
    Earth_Longest_Blackout_h, Roughness_m, _dx_m). Applies the hard physics guardrails.
    """
    metrics = {f: float(raw[f]) for f in FEATURES}
    tele = {"sun_longest_dark_h": raw.get("Sun_Longest_Dark_h"), "sun_longest_lit_h": raw.get("Sun_Longest_Lit_h"),
            "earth_longest_blackout_h": raw.get("Earth_Longest_Blackout_h"),
            "slope_baseline_ew_m": None if raw.get("_dx_m") is None else round(2 * raw["_dx_m"], 1)}
    warnings = list(warnings)

    pred = _predict(metrics)
    row = pred["X"]
    score_g, cls_g, masks = apply_guardrails(row, [pred["score"]], [pred["ml_class"]])
    triggered = [(code, msg, cap) for (code, _, _, cap, msg) in GUARDRAILS if bool(masks[code][0])]
    std = float(ensemble_std(row)[0])
    half = CI_Z * std if math.isfinite(std) else CI_Z * _cv_rmse()[0]
    rough = float(raw.get("Roughness_m") or 0.0)
    p_haz = float(pred["proba"][pred["classes"].index("Hazardous")])
    max_slope = prof["max_slope_deg"]
    sc_s, cls_s, sfm = apply_safety_factor(row, score_g, cls_g, [p_haz], [half], max_slope, [rough])
    score_final, safety = float(sc_s[0]), str(cls_s[0])
    sf_layers = [layer for layer in SAFETY_LAYERS if bool(sfm[layer][0])]
    cap = min([c for _, _, c in triggered] + ([SAFETY_CAP_SCORE] if sf_layers else []), default=None)
    eff = effective_max_slope(max_slope)
    s_ = metrics["Slope_deg"]
    sf_msgs = {
        "SLOPE_DERATING": (
            f"WARNING: Slope {s_:.1f}° exceeds the {eff:.1f}° operational limit ({max_slope:.1f}° tip-over limit minus the "
            f"{SLOPE_SAFETY_MARGIN_DEG:g}° safety margin for DEM uncertainty, FS≈{max_slope / max(eff, 1e-9):.2f}); NO-GO."
            if s_ > eff else
            f"WARNING: Slope {s_:.1f}° + {ROUGHNESS_SLOPE_WEIGHT:g} x roughness {rough:.1f} m = {s_ + ROUGHNESS_SLOPE_WEIGHT * rough:.1f}° "
            f"exceeds the {max_slope:.1f}° limit once DEM roughness is included; NO-GO."),
        "SCORE_BUFFER": (f"WARNING: Score {score_g[0]:.1f} (lower 95% bound {score_g[0] - half:.1f}) is inside the "
                         f"{SCORE_SAFETY_BUFFER:g}-pt safety buffer of the {ACCEPTABLE_MIN_SCORE:g} Acceptable threshold; "
                         "treated as Hazardous."),
        "HAZARD_PROB": (f"WARNING: P(Hazardous) = {p_haz:.2f} >= {HAZARD_PROB_THRESHOLD:g} risk-averse threshold; "
                        "class overridden to Hazardous."),
    }
    ood_feats = [f for f in FEATURES if not _dataset()[f].min() <= metrics[f] <= _dataset()[f].max()]
    for _, msg, _ in triggered:
        warnings.append(msg)
    for layer in sf_layers:
        warnings.append(sf_msgs[layer])
    if ood_feats:
        warnings.append("OOD: features outside the training range: " + ", ".join(ood_feats) + ".")

    default_comp, _, _ = _components(metrics)
    rule_score = sum(w * default_comp[k] for k, w in (("terrain", W_TERRAIN), ("solar", W_SOLAR), ("comms", W_COMMS)))
    rule_class = str(safety_class(metrics["Slope_deg"], rule_score))
    comp_p, ideal_p, limit_p = _components(metrics, prof)
    score_p = W_TERRAIN * comp_p["terrain"] + W_SOLAR * comp_p["solar"] + W_COMMS * comp_p["comms"]
    class_p = str(safety_class(metrics["Slope_deg"], score_p, ideal_p, limit_p))
    conf = confidence(metrics, pred, sources, rule_class, safety)
    flags = hazard_flags(metrics, tele, prof, sources, conf, lat)
    for layer in sf_layers:
        flags.insert(0, _flag(f"SAFETY_FACTOR_{layer}", "CRITICAL", sf_msgs[layer]))
    for code, msg, _ in triggered:
        flags.insert(0, _flag(f"GUARDRAIL_{code}", "CRITICAL", msg))
    just = engineering_justification(metrics, safety)
    for code, msg, cap_ in triggered:
        just.append(f"Guardrail {code}: {msg} Score capped at {cap_:.0f}.")
    for layer in sf_layers:
        just.append(f"Safety factor {layer}: {sf_msgs[layer]} Score capped at {SAFETY_CAP_SCORE:.0f}.")
    state = readiness(flags)
    ci = score_interval(score_final, std, cap)

    result = {
        "schema_version": SCHEMA_VERSION,
        "input": {"lat_deg": lat, "lon_deg_east": lon},
        "metrics": {**{k: round(v, 3) for k, v in metrics.items()},
                    **({"Roughness_m": round(raw["Roughness_m"], 3)} if raw.get("Roughness_m") is not None else {})},
        "component_scores": {k: round(v, 2) for k, v in default_comp.items()},
        "Suitability_Score": round(score_final, 2),
        "Safety_Class": safety,
        "class_probabilities": {c: round(float(p), 3) for c, p in zip(pred["classes"], pred["proba"])},
        "rule_based_check": {"Suitability_Score": round(float(rule_score), 2), "Safety_Class": rule_class},
        "justification": just,
        "data_sources": sources,
        "warnings": warnings,
        "window_utc": {"start": START_TIME, "stop": STOP_TIME, "step": STEP},
        "model": {"regressor": pred["reg"]["name"], "classifier": pred["clf"]["name"]},
        # ---- schema 2.0 additions ----
        "lander_profile": prof,
        "profile_assessment": {
            "slope_margin_deg": round(prof["max_slope_deg"] - metrics["Slope_deg"], 2),
            "sun_margin_pct": round(metrics["Sun_Visible_Pct"] - prof["min_sun_pct"], 2),
            "earth_margin_pct": round(metrics["Earth_Visible_Pct"] - prof["min_earth_pct"], 2),
            "meets_slope": bool(metrics["Slope_deg"] <= prof["max_slope_deg"]),
            "meets_sun": bool(metrics["Sun_Visible_Pct"] >= prof["min_sun_pct"]),
            "meets_earth": bool(metrics["Earth_Visible_Pct"] >= prof["min_earth_pct"]),
            "component_scores": {k: round(v, 2) for k, v in comp_p.items()},
            "rule_based_score": round(float(score_p), 2), "rule_based_class": class_p,
            "terrain_ideal_deg": round(ideal_p, 2),
            "note": "Rule-based recalculation with this profile's slope limits; the ML score/class above are trained on the default 5/15 deg rules."},
        "confidence": conf,
        "hazard_flags": flags,
        "operations_telemetry": {k: (None if v is None else round(v, 1)) for k, v in tele.items()},
        "mission_readiness": state,
        # ---- schema 2.1 additions (hybrid physics-ML) ----
        "Suitability_Score_raw_ml": round(pred["score"], 2),
        "mission_status_label": STATUS_LABELS[safety],
        "model_confidence_pct": round(float(pred["proba"].max()) * 100, 1),
        "score_uncertainty_95ci": ci,
        "guardrails": {"triggered": [c for c, _, _ in triggered], "score_cap": cap,
                       "class_overridden": bool(triggered) and pred["ml_class"] != "Hazardous"},
        "ood_warning": bool(ood_feats), "ood_features": ood_feats,
        "safety_factor": {
            "active": SAFETY_FACTOR_ACTIVE, "layers_triggered": sf_layers,
            "operational_slope_limit_deg": round(eff, 2), "mechanical_slope_limit_deg": round(float(max_slope), 2),
            "slope_safety_margin_deg": SLOPE_SAFETY_MARGIN_DEG,
            "factor_of_safety": round(max_slope / eff, 3) if eff > 0 else None,
            "slope_plus_half_roughness_deg": round(s_ + ROUGHNESS_SLOPE_WEIGHT * rough, 3),
            "score_buffer_pts": SCORE_SAFETY_BUFFER, "effective_acceptable_threshold": ACCEPTABLE_MIN_SCORE + SCORE_SAFETY_BUFFER,
            "conservative_score": round(float(score_g[0]) - half, 2),
            "hazard_probability_threshold": HAZARD_PROB_THRESHOLD, "p_hazardous": round(p_haz, 3),
            "class_before_safety_factor": str(cls_g[0]), "score_before_safety_factor": round(float(score_g[0]), 2)},
    }
    if explain_result:
        result["explanation"] = explain(metrics, pred, default_comp)
    return result


def evaluate_new_coordinates(lat: float, lon: float, allow_offline_fallback: bool = True, *,
                             profile: str | None = None, max_slope_deg: float | None = None,
                             min_sun_pct: float | None = None, min_earth_pct: float | None = None,
                             radius_km: float = 0.0, n_candidates: int = 3, force_offline: bool = False,
                             explain_result: bool = True) -> dict:
    """Evaluate a south-polar coordinate. Returns a JSON-serialisable dict (schema 2.0).

    Args:
        lat: selenographic latitude, deg, in [-90, -85].
        lon: east longitude, deg (any value; wrapped to 0-360).
        allow_offline_fallback: if a live source fails, interpolate from the CSV instead of raising.
        profile: 'generic' (default), 'small_robotic' or 'crewed_heavy' (illustrative envelopes).
        max_slope_deg / min_sun_pct / min_earth_pct: override the profile's tolerances.
        radius_km: if > 0, scan this radius (km, <= 25) and recommend the best nearby touchdown point.
        n_candidates: corridor candidates to fully evaluate.
        force_offline: skip all network access and use CSV interpolation.
        explain_result: include the feature-sensitivity block (set False for bulk scans).
    """
    lat, lon = _validate(lat, lon)
    prof = resolve_profile(profile, max_slope_deg, min_sun_pct, min_earth_pct)
    data = _collect(lat, lon, allow_offline_fallback, force_offline)
    result = assess_features(lat, lon, data["metrics"], data["sources"], data["warnings"], prof, explain_result)
    if radius_km and radius_km > 0:
        result["landing_corridor"] = landing_corridor(lat, lon, result, prof, radius_km, n_candidates,
                                                      allow_offline_fallback, force_offline)
    result["mission_brief"] = mission_brief(result)
    return result


def mission_brief(r: dict) -> str:
    """One-paragraph, human-readable summary for UI display."""
    m, p, c = r["metrics"], r["lander_profile"], r["confidence"]
    lo, hi = c["score_interval_95"]
    parts = [f"{r['mission_readiness']} for {p['name']} lander at ({r['input']['lat_deg']:.2f}, {r['input']['lon_deg_east']:.2f}): "
             f"suitability {r['Suitability_Score']:.1f}/100 (95% interval {lo:.0f}-{hi:.0f}), class {r['Safety_Class']}, "
             f"confidence {c['level']}."]
    parts.append(f"Slope {m['Slope_deg']:.1f} deg vs {p['max_slope_deg']:.0f} deg limit; Sun {m['Sun_Visible_Pct']:.0f}% "
                 f"(need {p['min_sun_pct']:.0f}%); Earth {r['metrics']['Earth_Visible_Pct']:.0f}% (need {p['min_earth_pct']:.0f}%).")
    if "explanation" in r:
        parts.append(f"Largest score loss: {r['explanation']['limiting_factor']} "
                     f"(-{r['explanation']['points_lost_by_component'][r['explanation']['limiting_factor']]:.1f} pts).")
    crit = [f for f in r["hazard_flags"] if f["severity"] in ("CRITICAL", "WARNING")]
    if crit:
        parts.append("Flags: " + "; ".join(f["code"] for f in crit) + ".")
    cor = r.get("landing_corridor")
    if cor and cor.get("status") == "ok":
        rec = cor["recommended"]
        if cor["recommended_action"] == "HOLD_TARGET":
            parts.append(f"Corridor scan ({cor['radius_km']:g} km): no better nearby point; hold the target.")
        else:
            parts.append(f"Corridor scan ({cor['radius_km']:g} km): relocate {rec['distance_m'] / 1000:.2f} km "
                         f"{_bearing_name(rec['bearing_deg'])} to ({rec['lat_deg']:.3f}, {rec['lon_deg_east']:.3f}), "
                         f"slope {rec['slope_deg']:.1f} deg, profile score +{cor['profile_score_gain_vs_target']:.1f}.")
    elif cor:
        parts.append(f"Corridor scan unavailable: {cor.get('reason')}.")
    return " ".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--offline", action="store_true", help="skip network, use CSV interpolation")
    ap.add_argument("--profile", choices=sorted(PROFILES), help="lander preset (default: generic)")
    ap.add_argument("--max-slope", type=float, help="override max landing slope, deg")
    ap.add_argument("--min-sun", type=float, help="override minimum Sun visibility, %%")
    ap.add_argument("--min-earth", type=float, help="override minimum Earth visibility, %%")
    ap.add_argument("--radius", type=float, default=0.0, help="scan radius in km for a safer nearby touchdown point")
    ap.add_argument("--candidates", type=int, default=3, help="corridor candidates to evaluate")
    a = ap.parse_args()
    try:
        print(json.dumps(evaluate_new_coordinates(
            a.lat, a.lon, force_offline=a.offline, profile=a.profile, max_slope_deg=a.max_slope,
            min_sun_pct=a.min_sun, min_earth_pct=a.min_earth, radius_km=a.radius, n_candidates=a.candidates), indent=2))
    except ValueError as exc:  # keep stdout machine-readable for the frontend
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
