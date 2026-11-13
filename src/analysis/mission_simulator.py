"""Mission physics engine behind the Lunar Landing Site Navigator dashboard.

Pure computation (no web / UI imports). One call, `evaluate_scenario`, turns the eight
dashboard controls into the unified output structure:

  primary_landing_decision, terrain_topography_physics, solar_illumination_visibility,
  earth_communication_status, power_generation, sunset_earthset_countdowns,
  xai_and_hazard_alerts, south_pole_map_and_top_5_sites, top_3_landing_windows,
  side_by_side_comparison (via `compare_scenarios`), csv_data_export (via `build_csv`).

Physics
  * Tower: raising the mast by h lowers the geometric horizon by acos(R/(R+h)); added to the
    Sun and Earth elevations.
  * Sun disc (0.265 deg radius): >= +0.265 direct, <= -0.265 dark, linear partial shadow between.
  * Power: P = S0 * eta * A * f_sun * max(0, sin(el_sun_eff + tilt)), S0 = 1361 W/m2, eta = 0.30.
    The panel is assumed to track the Sun in azimuth (only elevation/tilt matters).
Units: degrees, metres, hours (UTC), watts, kWh.
"""
from __future__ import annotations

import io
import csv
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predict_site as ps  # noqa: E402
from ephemeris_series import BASELINE_START, N_SAMPLES, STEP_HOURS, HourlySeries, get_hourly_series  # noqa: E402
from suitability import DATA_CSV, FEATURES, OUTPUTS_DIR, comms_score, solar_score, terrain_score  # noqa: E402

R_MOON_M = 1_737_400.0
R_MOON_KM = 1737.4
SUN_ANGULAR_RADIUS_DEG = 0.265
SOLAR_CONSTANT_W_M2 = 1361.0
PV_EFFICIENCY = 0.30
BASELINE_HOURS = N_SAMPLES - 1  # 1440 h between the first and last sample
PRESET_MATCH_KM = 0.05          # a coordinate this close to a dataset site is treated as that site
TOP_WINDOWS = 3
WINDOW_WEIGHTS = {"energy": 0.40, "sunlight": 0.30, "dte": 0.30}  # objective of the window optimiser
CSV_COLUMNS = ["timestamp_utc", "hour_index", "illumination_state", "sun_el_eff_deg", "dte_status",
               "earth_el_eff_deg", "time_to_sunset_hrs", "time_to_earthset_hrs", "power_watts",
               "cumulative_energy_kwh"]
DTE_CONNECTED = "Connected (Line-of-Sight Clear)"
DTE_BLOCKED = "Blocked (Signal Lost)"
STATES = np.array(["Total Darkness", "Partial Shadow", "Direct Sunlight"])
ROUGHNESS_CSV = OUTPUTS_DIR / "site_roughness.csv"

LIMITS = {"lat": (-90.0, -85.0), "lon": (0.0, 360.0), "max_slope_deg": (0.0, 15.0), "min_sun_pct": (0.0, 100.0),
          "min_earth_pct": (0.0, 100.0), "tower_height_m": (1.0, ps.MAX_TOWER_HEIGHT_M), "panel_tilt_deg": (0.0, 90.0),
          "panel_area_m2": (1.0, 50.0)}


# ----------------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------------
@dataclass
class Scenario:
    """The dashboard controls for one scenario (Site / Date / Hardware)."""
    lat: float | None = None
    lon: float | None = None
    site_id: str | None = None
    start_datetime_utc: datetime | None = None   # default: baseline start
    duration_hours: float = BASELINE_HOURS
    timeline_hour_index: int | None = None       # hour inside the mission window (0-based)
    timestamp_utc: datetime | None = None        # alternative to timeline_hour_index
    max_slope_deg: float = 15.0
    min_sun_pct: float = 50.0
    min_earth_pct: float = 40.0
    tower_height_m: float = 5.0
    panel_tilt_deg: float = 45.0
    panel_area_m2: float = 10.0
    priority_mode: str = "balanced"             # most_safety | balanced | most_power

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        names = cls.__dataclass_fields__
        d = {k: v for k, v in d.items() if k in names and v is not None}
        if "duration_days" in d:  # not a field; handled by callers that pass it explicitly
            d.pop("duration_days")
        for k in ("start_datetime_utc", "timestamp_utc"):
            if isinstance(d.get(k), str):
                d[k] = datetime.fromisoformat(d[k].replace("Z", "+00:00"))
        return cls(**d)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


@lru_cache(maxsize=1)
def _dataset() -> pd.DataFrame:
    return pd.read_csv(DATA_CSV)


@lru_cache(maxsize=1)
def _ranked() -> pd.DataFrame:
    return pd.read_csv(OUTPUTS_DIR / "ranked_lunar_sites.csv")


@lru_cache(maxsize=1)
def _roughness_table() -> dict:
    try:
        return pd.read_csv(ROUGHNESS_CSV).set_index("Site_ID")["Roughness_m"].to_dict()
    except Exception:
        return {}


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Great-circle distance (km) on the lunar sphere (R = 1737.4 km); inputs in degrees."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dlmb = p2 - p1, np.radians(np.asarray(lon2) - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * R_MOON_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def initial_bearing_deg(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Initial compass bearing (deg, 0 = N, clockwise) from point 1 to point(s) 2."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def validate(s: Scenario) -> None:
    """Range-check the controls (raises ValueError with a readable message)."""
    for name in ("max_slope_deg", "min_sun_pct", "min_earth_pct", "tower_height_m", "panel_tilt_deg", "panel_area_m2"):
        v, (lo, hi) = getattr(s, name), LIMITS[name]
        if v is None or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f"{name}={v} outside [{lo}, {hi}]")
    ps.mode_weights(s.priority_mode)  # raises ValueError for an unknown mode
    if s.site_id is None:
        if s.lat is None or s.lon is None:
            raise ValueError("provide site_id or both lat and lon")
        if not LIMITS["lat"][0] <= s.lat <= LIMITS["lat"][1]:
            raise ValueError(f"lat={s.lat} outside [-90, -85]")
        if not 0.0 <= s.lon <= 360.0:
            raise ValueError(f"lon={s.lon} outside [0, 360]")


def resolve_site(s: Scenario) -> tuple[float, float, dict | None]:
    """Return (lat, lon, dataset row or None) for a preset site_id, a near-preset coordinate, or a custom point."""
    ds = _dataset()
    if s.site_id is not None:
        hit = ds[ds["Site_ID"] == s.site_id]
        if hit.empty:
            raise ValueError(f"unknown site_id '{s.site_id}'")
        row = hit.iloc[0].to_dict()
        return float(row["Lat"]), float(row["Lon"]), row
    d = haversine_km(s.lat, s.lon, ds["Lat"].to_numpy(), ds["Lon"].to_numpy())
    k = int(np.argmin(d))
    if d[k] <= PRESET_MATCH_KM:
        row = ds.iloc[k].to_dict()
        return float(row["Lat"]), float(row["Lon"]), row
    return float(s.lat), float(s.lon) % 360.0, None


# ----------------------------------------------------------------------------
# Physics primitives (vectorised)
# ----------------------------------------------------------------------------
def tower_boost_deg(h_m: float) -> float:
    """Horizon depression gained by raising the mast to h_m: acos(R / (R + h)) in degrees."""
    return math.degrees(math.acos(R_MOON_M / (R_MOON_M + h_m)))


def sun_disc_fraction(sun_eff_deg: np.ndarray) -> np.ndarray:
    """Visible fraction of the solar disc: 1 above +0.265 deg, 0 below -0.265 deg, linear between."""
    return np.clip((np.asarray(sun_eff_deg) + SUN_ANGULAR_RADIUS_DEG) / (2 * SUN_ANGULAR_RADIUS_DEG), 0.0, 1.0)


def illumination_state(sun_eff_deg: np.ndarray) -> np.ndarray:
    """'Direct Sunlight' / 'Partial Shadow' / 'Total Darkness' per hour."""
    el = np.asarray(sun_eff_deg)
    idx = np.where(el >= SUN_ANGULAR_RADIUS_DEG, 2, np.where(el <= -SUN_ANGULAR_RADIUS_DEG, 0, 1))
    return STATES[idx]


def power_watts(sun_eff_deg: np.ndarray, area_m2: float, tilt_deg: float) -> np.ndarray:
    """Electrical power (W): S0 * eta * A * f_sun * max(0, sin(el_sun_eff + tilt))."""
    el = np.asarray(sun_eff_deg, dtype=float)
    return (SOLAR_CONSTANT_W_M2 * PV_EFFICIENCY * area_m2 * sun_disc_fraction(el)
            * np.maximum(0.0, np.sin(np.radians(el + tilt_deg))))


def crossing_times(el: np.ndarray, direction: str) -> np.ndarray:
    """Fractional sample indices where elevation crosses 0 ('down' = set, 'up' = rise), linearly interpolated."""
    a, b = el[:-1], el[1:]
    m = (a > 0) & (b <= 0) if direction == "down" else (a <= 0) & (b > 0)
    i = np.flatnonzero(m)
    return i + a[i] / (a[i] - b[i])


def next_event(el: np.ndarray, idx: int, start_utc: datetime) -> dict:
    """Time from sample `idx` to the next horizon crossing (set if currently above, rise if below)."""
    lit = bool(el[idx] > 0)
    ct = crossing_times(el, "down" if lit else "up")
    k = int(np.searchsorted(ct, idx, side="left"))
    out = {"currently_above_horizon": lit, "event": ("set" if lit else "rise")}
    if k >= len(ct):
        return {**out, "hours": None, "days": None, "hours_component": None, "minutes": None, "formatted": None,
                "event_time_utc": None, "note": f"no {out['event']} before the end of the ephemeris window"}
    hrs = float(ct[k] - idx)
    total_min = int(round(hrs * 60))
    d, rem = divmod(total_min, 1440)
    h, m = divmod(rem, 60)
    return {**out, "hours": round(hrs, 3), "days": d, "hours_component": h, "minutes": m,
            "formatted": f"{d}d {h}h {m}m", "event_time_utc": _iso(start_utc + timedelta(hours=float(ct[k]))), "note": None}


# ----------------------------------------------------------------------------
# Mission context
# ----------------------------------------------------------------------------
@dataclass
class Context:
    lat: float
    lon: float
    row: dict | None
    series: HourlySeries
    boost_deg: float
    sun_eff: np.ndarray          # full 1441-sample baseline, tower boost applied
    earth_eff: np.ndarray
    start_idx: int
    length: int                  # mission duration in samples/hours

    @property
    def win(self) -> slice:
        return slice(self.start_idx, self.start_idx + self.length)

    @property
    def start_utc(self) -> datetime:
        return BASELINE_START + timedelta(hours=self.start_idx * STEP_HOURS)


def build_context(s: Scenario, series_mode: str = "auto") -> Context:
    """Validate, resolve the site, fetch the hourly series and apply the tower boost."""
    validate(s)
    lat, lon, row = resolve_site(s)
    start = _utc(s.start_datetime_utc) if s.start_datetime_utc else BASELINE_START
    start_idx = int(round((start - BASELINE_START).total_seconds() / 3600.0))
    length = int(round(s.duration_hours))
    if length < 1:
        raise ValueError("duration_hours must be >= 1")
    if not 0 <= start_idx < N_SAMPLES:
        raise ValueError(f"start_datetime_utc must lie within {_iso(BASELINE_START)} .. "
                         f"{_iso(BASELINE_START + timedelta(hours=BASELINE_HOURS))}")
    if start_idx + length > N_SAMPLES:
        raise ValueError(f"mission window exceeds the ephemeris baseline; max duration from this start is "
                         f"{N_SAMPLES - start_idx} h")
    series = get_hourly_series(lat, lon, site_row=row, mode=series_mode)
    boost = tower_boost_deg(s.tower_height_m)
    return Context(lat, lon, row, series, boost, series.sun_el + boost, series.earth_el + boost, start_idx, length)


def timeline_index(s: Scenario, ctx: Context) -> int:
    """Resolve the slider position (hour inside the mission window)."""
    if s.timestamp_utc is not None:
        idx = int(round((_utc(s.timestamp_utc) - ctx.start_utc).total_seconds() / 3600.0))
    else:
        idx = 0 if s.timeline_hour_index is None else int(s.timeline_hour_index)
    if not 0 <= idx < ctx.length:
        raise ValueError(f"timeline index {idx} outside the mission window [0, {ctx.length - 1}]")
    return idx


def window_features(ctx: Context, mast_free: bool = False) -> dict:
    """Dataset-style Sun/Earth features of the mission window (effective elevations, incl. tower boost unless mast_free)."""
    sun, earth = ctx.sun_eff[ctx.win], ctx.earth_eff[ctx.win]
    if mast_free:
        sun, earth = sun - ctx.boost_deg, earth - ctx.boost_deg
    out = {"Sun_Visible_Pct": float((sun > 0).mean() * 100), "Sun_Avg_El": float(sun.mean()),
           "Sun_Max_El": float(sun.max()), "Earth_Visible_Pct": float((earth > 0).mean() * 100),
           "Earth_Avg_El": float(earth.mean()), "Earth_Max_El": float(earth.max())}
    out["Sun_Longest_Dark_h"] = ps._longest_run_hours(sun <= 0)
    out["Sun_Longest_Lit_h"] = ps._longest_run_hours(sun > 0)
    out["Earth_Longest_Blackout_h"] = ps._longest_run_hours(earth <= 0)
    return out


def terrain_for(ctx: Context) -> tuple[dict, str, list[str]]:
    """Elevation / slope / roughness for the site: dataset for presets, LOLA DEM (non-blocking) otherwise."""
    warnings: list[str] = []
    if ctx.row is not None:
        t = {"Elevation_m": float(ctx.row["Elevation_m"]), "Slope_deg": float(ctx.row["Slope_deg"]),
             "Roughness_m": _roughness_table().get(ctx.row["Site_ID"]),
             "_dx_m": ps.DEM_BASE_PIXEL_M * math.cos(math.radians(ctx.lat))}
        return t, "dataset (LOLA DEM, precomputed)", warnings
    try:
        return ps.get_terrain_metrics_fast(ctx.lat, ctx.lon), "USGS LOLA 118 m DEM", warnings
    except Exception as exc:
        t = ps.interpolate_from_dataset(ctx.lat, ctx.lon, ["Elevation_m", "Slope_deg"])
        t["Roughness_m"] = None
        warnings.append(f"LOLA DEM unavailable ({type(exc).__name__}: {str(exc)[:100]}); "
                        "elevation/slope interpolated from the 100-site dataset.")
        return t, "dataset IDW interpolation (fallback)", warnings


# ----------------------------------------------------------------------------
# Map + alternatives
# ----------------------------------------------------------------------------
def passes_filters(r: pd.DataFrame, max_slope_deg: float, min_sun_pct: float, min_earth_pct: float) -> pd.Series:
    """Vehicle-constraint mask. Slope uses the derated operational limit (max - 1.5 deg safety margin) and
    must also satisfy slope + 0.5 * roughness <= max, so the dashboard never recommends a site the engine rates NO-GO."""
    eff = ps.effective_max_slope(max_slope_deg)
    rough = r["Site_ID"].map(_roughness_table()).fillna(0.0)
    return ((r["Slope_deg"] <= eff) & (r["Slope_deg"] + ps.ROUGHNESS_SLOPE_WEIGHT * rough <= max_slope_deg)
            & (r["Sun_Visible_Pct"] >= min_sun_pct) & (r["Earth_Visible_Pct"] >= min_earth_pct))


def filter_sites(max_slope_deg: float, min_sun_pct: float, min_earth_pct: float) -> pd.DataFrame:
    """Rows of ranked_lunar_sites.csv that satisfy all vehicle constraints (rank order kept)."""
    r = _ranked()
    return r[passes_filters(r, max_slope_deg, min_sun_pct, min_earth_pct)]


def mode_scores(r: pd.DataFrame, mode: str) -> pd.Series:
    """Rule-based composite score of every row under a priority mode's (terrain, solar, comms) weights."""
    wt, ws, wc = ps.mode_weights(mode)
    return (wt * terrain_score(r["Slope_deg"]) + ws * solar_score(r["Sun_Visible_Pct"], r["Sun_Max_El"])
            + wc * comms_score(r["Earth_Visible_Pct"], r["Earth_Avg_El"]))


def display_class(r: pd.DataFrame) -> pd.Series:
    """Rule class with the safety-factor slope derating applied (what the dashboard colours the 3-D markers with)."""
    rough = r["Site_ID"].map(_roughness_table()).fillna(0.0)
    bad = (r["Slope_deg"] > ps.effective_max_slope(15.0)) | (r["Slope_deg"] + ps.ROUGHNESS_SLOPE_WEIGHT * rough > 15.0)
    return r["Safety_Class"].where(~bad, "Hazardous")


def _ranked_for_mode(mode: str) -> pd.DataFrame:
    """ranked_lunar_sites.csv with mode_score, rank_in_mode (1 = best under this mode) and display_class."""
    r = _ranked().copy()
    r["mode_score"] = mode_scores(r, mode)
    r["rank_in_mode"] = r["mode_score"].rank(ascending=False, method="first").astype(int)
    r["display_class"] = display_class(r)
    return r


def _site_record(r: pd.Series, lat: float, lon: float) -> dict:
    return {"rank": int(r["rank_in_mode"]), "balanced_rank": int(r["Rank"]), "site_id": r["Site_ID"],
            "lat_deg": float(r["Lat"]), "lon_deg_east": float(r["Lon"]),
            "Suitability_Score": round(float(r["mode_score"]), 2), "Safety_Class": r["display_class"],
            "slope_deg": float(r["Slope_deg"]), "Sun_Visible_Pct": float(r["Sun_Visible_Pct"]),
            "Earth_Visible_Pct": float(r["Earth_Visible_Pct"]),
            "distance_km": round(float(haversine_km(lat, lon, r["Lat"], r["Lon"])), 3),
            "bearing_deg": round(float(initial_bearing_deg(lat, lon, r["Lat"], r["Lon"])), 1)}


def top_alternatives(lat: float, lon: float, s: Scenario, n: int = 5, exclude_site_id: str | None = None) -> dict:
    """Top-n sites under the scenario's priority mode that pass the (safety-derated) vehicle filters, with distance and bearing."""
    r = _ranked_for_mode(s.priority_mode)
    f = r[passes_filters(r, s.max_slope_deg, s.min_sun_pct, s.min_earth_pct)].sort_values("mode_score", ascending=False)
    f = f[f["Site_ID"] != exclude_site_id] if exclude_site_id else f
    top = [_site_record(row, lat, lon) for _, row in f.head(n).iterrows()]
    return {"selected": {"lat_deg": lat, "lon_deg_east": lon, "polar_x_deg": round((90 + lat) * math.cos(math.radians(lon)), 4),
                         "polar_y_deg": round((90 + lat) * math.sin(math.radians(lon)), 4)},
            "priority_mode": s.priority_mode, "mode_weights": dict(zip(("terrain", "solar", "comms"), ps.mode_weights(s.priority_mode))),
            "filters": {"max_slope_deg": s.max_slope_deg, "effective_max_slope_deg": ps.effective_max_slope(s.max_slope_deg),
                        "slope_safety_margin_deg": ps.SLOPE_SAFETY_MARGIN_DEG, "min_sun_pct": s.min_sun_pct,
                        "min_earth_pct": s.min_earth_pct},
            "n_sites_passing_filters": int(len(f)), "top5_filtered": top,
            "note": "Ranked by the rule-based composite under the active priority mode; distances on a 1737.4 km sphere."}


def sites_overview(max_slope_deg: float = 15.0, min_sun_pct: float = 50.0, min_earth_pct: float = 40.0,
                   lat: float = -90.0, lon: float = 0.0, priority_mode: str = "balanced") -> dict:
    """All 100 preset sites (with passes_filters, mode score/rank) plus the filtered top 5 from (lat, lon)."""
    s = Scenario(lat=lat, lon=lon, max_slope_deg=max_slope_deg, min_sun_pct=min_sun_pct, min_earth_pct=min_earth_pct,
                 priority_mode=priority_mode)
    validate(s)
    r = _ranked_for_mode(priority_mode).sort_values("rank_in_mode")
    ok = passes_filters(r, max_slope_deg, min_sun_pct, min_earth_pct)
    sites = []
    for (_, row), passes in zip(r.iterrows(), ok):
        rec = _site_record(row, lat, lon)
        rec.update({"passes_filters": bool(passes), "Elevation_m": float(row["Elevation_m"]),
                    "Sun_Avg_El": float(row["Sun_Avg_El"]), "Sun_Max_El": float(row["Sun_Max_El"]),
                    "Earth_Avg_El": float(row["Earth_Avg_El"]), "Earth_Max_El": float(row["Earth_Max_El"]),
                    "rule_class": row["Safety_Class"], "Roughness_m": _roughness_table().get(row["Site_ID"])})
        sites.append(rec)
    alt = top_alternatives(lat, lon, s)
    return {"n_sites": len(sites), "sites": sites, "top5_filtered": alt["top5_filtered"], "priority_mode": priority_mode,
            "mode_weights": alt["mode_weights"], "n_sites_passing_filters": alt["n_sites_passing_filters"],
            "filters": alt["filters"], "reference_point": {"lat_deg": lat, "lon_deg_east": lon}}


# ----------------------------------------------------------------------------
# Window optimiser
# ----------------------------------------------------------------------------
def best_windows(ctx: Context, s: Scenario, n: int = TOP_WINDOWS) -> dict:
    """Sliding-window search over the 60-day baseline for the `n` best non-overlapping start times.

    For every start the window (length = duration_hours) is scored by
    objective = 0.40 * energy/max_energy + 0.30 * sunlight_fraction + 0.30 * DTE_uptime_fraction.
    """
    L = ctx.length
    lit = (ctx.sun_eff > 0).astype(float)
    dte = (ctx.earth_eff > 0).astype(float)
    P = power_watts(ctx.sun_eff, s.panel_area_m2, s.panel_tilt_deg)
    cs = lambda a: np.concatenate([[0.0], np.cumsum(a)])  # noqa: E731
    c_lit, c_dte, c_p, c_joint = cs(lit), cs(dte), cs(P), cs(lit * dte)
    starts = np.arange(0, N_SAMPLES - L + 1)
    sun_h, dte_h = c_lit[starts + L] - c_lit[starts], c_dte[starts + L] - c_dte[starts]
    joint_h, e_kwh = c_joint[starts + L] - c_joint[starts], (c_p[starts + L] - c_p[starts]) / 1000.0
    e_norm = e_kwh / e_kwh.max() if e_kwh.max() > 0 else np.zeros_like(e_kwh)
    obj = (WINDOW_WEIGHTS["energy"] * e_norm + WINDOW_WEIGHTS["sunlight"] * sun_h / L
           + WINDOW_WEIGHTS["dte"] * dte_h / L)
    chosen: list[int] = []
    for k in np.argsort(-obj, kind="stable"):
        if all(abs(int(starts[k]) - int(starts[c])) >= L for c in chosen):
            chosen.append(int(k))
        if len(chosen) == n:
            break
    out = []
    for rank, k in enumerate(chosen, 1):
        st = BASELINE_START + timedelta(hours=float(starts[k]))
        out.append({"rank": rank, "start_utc": _iso(st), "end_utc": _iso(st + timedelta(hours=L)),
                    "start_hour_index": int(starts[k]), "duration_hours": L,
                    "sunlight_hours": round(float(sun_h[k]), 1), "dte_uptime_hours": round(float(dte_h[k]), 1),
                    "dte_uptime_pct": round(float(dte_h[k] / L * 100), 2),
                    "simultaneous_sun_and_dte_hours": round(float(joint_h[k]), 1),
                    "energy_kwh": round(float(e_kwh[k]), 3), "average_power_watts": round(float(e_kwh[k] * 1000 / L), 2),
                    "objective": round(float(obj[k]), 4)})
    return {"windows": out, "objective": "0.40*energy_norm + 0.30*sunlight_fraction + 0.30*dte_fraction",
            "weights": WINDOW_WEIGHTS, "candidate_starts_evaluated": int(len(starts)),
            "note": (None if len(out) == n else
                     f"Only {len(out)} non-overlapping window(s) of {L} h fit inside the 60-day baseline.")}


# ----------------------------------------------------------------------------
# Public: evaluate / compare / export
# ----------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _baseline_iso() -> list[str]:
    return [_iso(BASELINE_START + timedelta(hours=i * STEP_HOURS)) for i in range(N_SAMPLES)]


def _timeline_columns(ctx: Context, P: np.ndarray, state: np.ndarray, f_sun: np.ndarray) -> dict:
    w = ctx.win
    cum = np.cumsum(P[w]) / 1000.0
    return {"timestamp_utc": _baseline_iso()[w], "hour_index": list(range(ctx.length)),
            "illumination_state": state[w].tolist(), "sun_disc_fraction": np.round(f_sun[w], 4).tolist(),
            "sun_el_eff_deg": np.round(ctx.sun_eff[w], 4).tolist(),
            "dte_status": np.where(ctx.earth_eff[w] > 0, DTE_CONNECTED, DTE_BLOCKED).tolist(),
            "earth_el_eff_deg": np.round(ctx.earth_eff[w], 4).tolist(),
            "power_watts": np.round(P[w], 3).tolist(), "cumulative_energy_kwh": np.round(cum, 5).tolist()}


def evaluate_scenario(s: Scenario, include_timeline: bool = True, series_mode: str = "auto",
                      include_windows: bool = True, explain: bool = True, keep_internal: bool = False) -> dict:
    """Evaluate one scenario and return dashboard outputs 1-9 (+ timeline and CSV metadata)."""
    t0 = time.perf_counter()
    ctx = build_context(s, series_mode)
    idx = timeline_index(s, ctx)
    w, abs_idx = ctx.win, ctx.start_idx + idx

    feats = window_features(ctx)
    terrain, terrain_src, tw = terrain_for(ctx)
    raw = {**{f: feats[f] for f in FEATURES if f in feats}, "Elevation_m": terrain["Elevation_m"],
           "Slope_deg": terrain["Slope_deg"], "Roughness_m": terrain.get("Roughness_m"), "_dx_m": terrain.get("_dx_m"),
           **{k: feats[k] for k in ("Sun_Longest_Dark_h", "Sun_Longest_Lit_h", "Earth_Longest_Blackout_h")},
           "_ood_ref": {f: v for f, v in window_features(ctx, mast_free=True).items() if f in FEATURES}}
    eph_src = {"horizons_cache": "JPL Horizons (cached hourly series)", "horizons_live": "JPL Horizons API (hourly series)",
               "analytic_calibrated": "analytic curve calibrated to dataset statistics",
               "analytic_model": "analytic physics model (uncalibrated fallback)"}[ctx.series.source]
    prof = ps.resolve_profile(None, s.max_slope_deg, s.min_sun_pct, s.min_earth_pct)
    res = ps.assess_features(ctx.lat, ctx.lon, raw, {"ephemeris": eph_src, "terrain": terrain_src},
                             tw + list(ctx.series.notes), prof, explain_result=explain, priority_mode=s.priority_mode)

    f_sun = sun_disc_fraction(ctx.sun_eff)
    state = illumination_state(ctx.sun_eff)
    P = power_watts(ctx.sun_eff, s.panel_area_m2, s.panel_tilt_deg)
    Pw = P[w]
    sun_now, earth_now = float(ctx.sun_eff[abs_idx]), float(ctx.earth_eff[abs_idx])
    sun_hours = float((ctx.sun_eff[w] > 0).sum())
    cum_now = float(Pw[: idx + 1].sum() / 1000.0)

    sun_ev = next_event(ctx.sun_eff, abs_idx, BASELINE_START)
    earth_ev = next_event(ctx.earth_eff, abs_idx, BASELINE_START)
    sun_key = "time_to_sunset" if sun_ev["currently_above_horizon"] else "time_to_sunrise"
    earth_key = "time_to_earthset" if earth_ev["currently_above_horizon"] else "time_to_earthrise"

    flags = res["hazard_flags"]
    alerts_warnings = list(res["warnings"])
    dark_h = res["operations_telemetry"].get("sun_longest_dark_h")
    if dark_h and dark_h > ps.LONG_DARK_HOURS:
        alerts_warnings.append(f"Prolonged crater shadowing: longest continuous Sun outage {dark_h:.0f} h in this window.")
    blk = res["operations_telemetry"].get("earth_longest_blackout_h")
    if blk and blk > ps.LONG_BLACKOUT_HOURS:
        alerts_warnings.append(f"Comms blackout risk: longest continuous Earth outage {blk:.0f} h in this window.")
    if terrain["Slope_deg"] > s.max_slope_deg:
        alerts_warnings.append(f"Tip-over risk: slope {terrain['Slope_deg']:.1f} deg exceeds your {s.max_slope_deg:g} deg limit.")
    elif terrain["Slope_deg"] > ps.MARGINAL_SLOPE_FRACTION * s.max_slope_deg:
        alerts_warnings.append(f"Tip-over margin thin: slope {terrain['Slope_deg']:.1f} deg vs {s.max_slope_deg:g} deg limit.")

    out = {
        "schema_version": "3.0",
        "scenario": {"lat_deg": ctx.lat, "lon_deg_east": ctx.lon, "site_id": ctx.row["Site_ID"] if ctx.row else None,
                     "is_preset_site": ctx.row is not None, "start_datetime_utc": _iso(ctx.start_utc),
                     "end_datetime_utc": _iso(ctx.start_utc + timedelta(hours=ctx.length)),
                     "duration_hours": ctx.length, "timeline_hour_index": idx,
                     "timestamp_utc": _iso(ctx.start_utc + timedelta(hours=idx)),
                     "priority_mode": s.priority_mode,
                     "vehicle": {"max_slope_deg": s.max_slope_deg, "min_sun_pct": s.min_sun_pct,
                                 "min_earth_pct": s.min_earth_pct},
                     "hardware": {"tower_height_m": s.tower_height_m, "tower_horizon_boost_deg": round(ctx.boost_deg, 5),
                                  "panel_tilt_deg": s.panel_tilt_deg, "panel_area_m2": s.panel_area_m2}},
        "primary_landing_decision": {
            "Suitability_Score": res["Suitability_Score"], "score_uncertainty_95ci": res["score_uncertainty_95ci"],
            "Safety_Class": res["Safety_Class"], "mission_status_label": res["mission_status_label"],
            "model_confidence_pct": res["model_confidence_pct"], "class_probabilities": res["class_probabilities"],
            "Suitability_Score_raw_ml": res["Suitability_Score_raw_ml"], "guardrails": res["guardrails"],
            "safety_factor": res["safety_factor"], "priority_mode": res["priority_mode"], "mode_weights": res["mode_weights"],
            "Suitability_Score_balanced": res["Suitability_Score_balanced"],
            "mission_readiness": res["mission_readiness"], "ood_warning": res["ood_warning"]},
        "terrain_topography_physics": {"Slope_deg": round(terrain["Slope_deg"], 3),
                                       "Elevation_m": round(terrain["Elevation_m"], 2),
                                       "Roughness_m": None if terrain.get("Roughness_m") is None else round(terrain["Roughness_m"], 3),
                                       "source": terrain_src},
        "solar_illumination_visibility": {
            "illumination_state": str(state[abs_idx]), "sun_disc_fraction": round(float(f_sun[abs_idx]), 4),
            "Sun_Visible_Pct": round(feats["Sun_Visible_Pct"], 3), "live_sun_elevation_deg": round(sun_now, 4),
            "Sun_Max_El": round(feats["Sun_Max_El"], 3), "Sun_Avg_El": round(feats["Sun_Avg_El"], 3),
            "sunlight_hours": sun_hours, "longest_dark_hours": feats["Sun_Longest_Dark_h"],
            "tower_horizon_boost_deg": round(ctx.boost_deg, 5), "ephemeris_source": ctx.series.source},
        "earth_communication_status": {
            "dte_status": DTE_CONNECTED if earth_now > 0 else DTE_BLOCKED,
            "Earth_Visible_Pct": round(feats["Earth_Visible_Pct"], 3), "live_earth_elevation_deg": round(earth_now, 4),
            "Earth_Max_El": round(feats["Earth_Max_El"], 3), "Earth_Avg_El": round(feats["Earth_Avg_El"], 3),
            "longest_blackout_hours": feats["Earth_Longest_Blackout_h"]},
        "power_generation": {
            "real_time_power_watts": round(float(Pw[idx]), 2), "peak_power_watts": round(float(Pw.max()), 2),
            "average_power_watts": round(float(Pw.mean()), 2),
            "total_accumulated_energy_kwh": round(float(Pw.sum() / 1000.0), 3),
            "accumulated_energy_to_current_hour_kwh": round(cum_now, 3),
            "model": {"solar_constant_w_m2": SOLAR_CONSTANT_W_M2, "pv_efficiency": PV_EFFICIENCY,
                      "formula": "S0*eta*A*f_sun*max(0,sin(el_sun_eff+tilt)); sun-tracking in azimuth assumed"}},
        "sunset_earthset_countdowns": {
            "from_timestamp_utc": _iso(BASELINE_START + timedelta(hours=abs_idx)),
            "time_to_sunset": sun_ev if sun_key == "time_to_sunset" else None,
            "time_to_sunrise": sun_ev if sun_key == "time_to_sunrise" else None,
            "time_to_earthset": earth_ev if earth_key == "time_to_earthset" else None,
            "time_to_earthrise": earth_ev if earth_key == "time_to_earthrise" else None,
            "resolution": "linear interpolation of the hourly horizon crossing (about 1 min); scans to 2027-01-12"},
        "xai_and_hazard_alerts": {
            "justifications": res["justification"], "warnings": alerts_warnings,
            "component_scores": res["component_scores"], "hazard_flags": flags,
            "confidence": res["confidence"], "ood_warning": res["ood_warning"], "ood_features": res["ood_features"],
            **({"explanation": res["explanation"]} if "explanation" in res else {})},
        "south_pole_map_and_top_5_sites": top_alternatives(ctx.lat, ctx.lon, s,
                                                           exclude_site_id=ctx.row["Site_ID"] if ctx.row else None),
        "side_by_side_comparison": None,
        "csv_data_export": {"endpoint": "/api/export-csv", "filename": "mission_telemetry_export.csv",
                            "columns": CSV_COLUMNS, "row_count": ctx.length},
        "data_sources": res["data_sources"],
    }
    if include_windows:
        out["top_3_landing_windows"] = best_windows(ctx, s)
    if include_timeline:
        out["timeline"] = _timeline_columns(ctx, P, state, f_sun)
    out["_metrics"] = {"sunlight_hours": sun_hours, "comms_uptime_pct": feats["Earth_Visible_Pct"],
                       "average_power_watts": float(Pw.mean()), "peak_power_watts": float(Pw.max()),
                       "energy_kwh": float(Pw.sum() / 1000.0), "slope_deg": terrain["Slope_deg"],
                       "score": res["Suitability_Score"]}
    out["compute_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if not keep_internal:
        out.pop("_metrics")
    return out


def compare_scenarios(a: Scenario, b: Scenario, include_timeline: bool = False, series_mode: str = "auto") -> dict:
    """Output #10: both evaluations plus exact numerical deltas (B minus A)."""
    ea = evaluate_scenario(a, include_timeline, series_mode, keep_internal=True)
    eb = evaluate_scenario(b, include_timeline, series_mode, keep_internal=True)
    ma, mb = ea.pop("_metrics"), eb.pop("_metrics")
    d = lambda k: round(mb[k] - ma[k], 4)  # noqa: E731
    deltas = {"delta_suitability_score": d("score"), "delta_sunlight_hours": d("sunlight_hours"),
              "delta_power_watts": d("average_power_watts"), "delta_peak_power_watts": d("peak_power_watts"),
              "delta_energy_kwh": d("energy_kwh"), "delta_comms_uptime_pct": d("comms_uptime_pct"),
              "delta_slope_deg": d("slope_deg")}
    better = "B" if (deltas["delta_suitability_score"], deltas["delta_energy_kwh"]) > (0, 0) else \
        "A" if (deltas["delta_suitability_score"], deltas["delta_energy_kwh"]) < (0, 0) else "tie"
    return {"side_by_side_comparison": {
        "convention": "delta = Scenario B - Scenario A; delta_power_watts is the mission-average power",
        "scenario_a": ea, "scenario_b": eb, "deltas": deltas, "higher_score_scenario": better}}


def _fmt(v: float | None) -> str:
    return "" if v is None or not math.isfinite(v) else f"{v:.4f}"


def build_csv(s: Scenario, series_mode: str = "auto") -> str:
    """Output #11: hourly telemetry rows for the mission window as CSV text.

    time_to_sunset_hrs / time_to_earthset_hrs are hours until the next lit->dark / visible->blocked
    transition counted from each row (blank if none occurs before 2027-01-12).
    """
    ctx = build_context(s, series_mode)
    f_sun, state = sun_disc_fraction(ctx.sun_eff), illumination_state(ctx.sun_eff)
    P = power_watts(ctx.sun_eff, s.panel_area_m2, s.panel_tilt_deg)
    idx_abs = np.arange(ctx.start_idx, ctx.start_idx + ctx.length)

    def to_next(el):
        ct = crossing_times(el, "down")
        out = np.full(len(idx_abs), np.nan)
        if len(ct):
            k = np.searchsorted(ct, idx_abs, side="left")
            ok = k < len(ct)
            out[ok] = ct[k[ok]] - idx_abs[ok]
        return out

    t_sun, t_earth = to_next(ctx.sun_eff), to_next(ctx.earth_eff)
    cum = np.cumsum(P[ctx.win]) / 1000.0
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(CSV_COLUMNS)
    iso = _baseline_iso()
    for i, a in enumerate(idx_abs):
        wr.writerow([iso[a], i, state[a], f"{ctx.sun_eff[a]:.4f}", DTE_CONNECTED if ctx.earth_eff[a] > 0 else DTE_BLOCKED,
                     f"{ctx.earth_eff[a]:.4f}", _fmt(t_sun[i]), _fmt(t_earth[i]), f"{P[a]:.3f}", f"{cum[i]:.5f}"])
    return buf.getvalue()


def to_jsonable(o):
    """Recursively convert numpy types / NaN to plain JSON-safe Python values."""
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return to_jsonable(o.tolist())
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o
