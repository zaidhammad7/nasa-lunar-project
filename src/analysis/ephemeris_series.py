"""Hourly Sun / Earth elevation series for a lunar surface point.

Sources, in order of preference (see `get_hourly_series`):
  1. cache   - real JPL Horizons series previously stored in ./ephemeris_cache/*.npz
  2. live    - JPL Horizons API (about 7 s per body), stored in the cache
  3. analytic- deterministic physics model (Sun: synodic sub-solar sweep; Earth: optical
               libration), instant. For the 100 preset sites it is additionally
               remapped so the window statistics equal the dataset's exactly
               (Sun/Earth Visible_Pct, Avg_El, Max_El).

Units: elevations in degrees above the local flat horizon, time in UTC, step 1 h.
The baseline window is 2026-11-13 00:00 .. 2027-01-12 00:00 UTC inclusive (1441 samples).
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from suitability import REPO_ROOT

# ---- Window / API constants ------------------------------------------------
HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
START_TIME, STOP_TIME, STEP = "2026-11-13", "2027-01-12", "1h"
BASELINE_START = datetime(2026, 11, 13, tzinfo=timezone.utc)
N_SAMPLES = 1441
STEP_HOURS = 1.0
HTTP_TIMEOUT_S = 60
HORIZONS_RETRIES = 3
LIVE_BUDGET_S = 3.0  # "auto" mode: wait this long for Horizons before answering analytically
CACHE_DIR = REPO_ROOT / "ephemeris_cache"
CACHE_DECIMALS = 3   # cache key resolution (~30 m); preset sites carry 4 decimals

# ---- Analytic model constants ----------------------------------------------
R_MOON_KM = 1737.4
EARTH_DISTANCE_KM = 384400.0
P_SYNODIC_H = 29.530589 * 24.0       # Sun's sweep around the sky: 708.7 h
P_DRACONIC_H = 27.212221 * 24.0      # latitude libration of the sub-Earth point: 653.1 h
P_ANOMALISTIC_H = 27.554550 * 24.0   # longitude libration of the sub-Earth point: 661.3 h
# Least-squares fit to real Horizons series at Auto_SP_099, 075, 36 and 065 (the other four cached
# sites were held out: Sun RMSE ~0.06 deg / corr ~1.0, Earth RMSE ~0.45 deg / corr 0.998).
# Sun: sub-solar longitude at t=0 (deg E), sub-solar latitude offset and drift (deg).
# Earth: libration amplitudes (deg) and phases (rad); l_amp sits at its fit bound, i.e. it is an
# effective value absorbing unmodelled physical libration terms.
MODEL_PARAMS = {
    "sun": {"lam0": 139.64631912569732, "d0": -1.3096994682591019, "d1": 0.38634871211499355},
    "earth": {"b_amp": 6.556147658458688, "b_phase": 2.216299918376506,
              "l_amp": 12.0, "l_phase": 3.285194062826637},
}

_HORIZONS_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="horizons")
_INFLIGHT: dict[str, object] = {}
_INFLIGHT_LOCK = threading.Lock()
_MEMORY: dict[tuple, "HourlySeries"] = {}


@dataclass
class HourlySeries:
    """Hourly elevation arrays (deg) over the 1441-sample baseline window."""
    sun_el: np.ndarray
    earth_el: np.ndarray
    source: str                     # "horizons_cache" | "horizons_live" | "analytic_calibrated" | "analytic_model"
    calibrated: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def is_real(self) -> bool:
        return self.source.startswith("horizons")


def timestamps(n: int = N_SAMPLES, start: datetime = BASELINE_START) -> list[datetime]:
    """UTC timestamps of the hourly baseline grid."""
    return [start + timedelta(hours=STEP_HOURS * i) for i in range(n)]


# ----------------------------------------------------------------------------
# JPL Horizons (live)
# ----------------------------------------------------------------------------
def horizons_get(params: dict) -> dict:
    """GET the Horizons API one request at a time, retrying transient 429/5xx errors.

    Horizons answers 503 when hit concurrently, so requests are serialised process-wide.
    """
    last: Exception | None = None
    for attempt in range(HORIZONS_RETRIES):
        with _HORIZONS_LOCK:
            try:
                resp = requests.get(HORIZONS_URL, params=params, timeout=HTTP_TIMEOUT_S)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{resp.status_code} from Horizons", response=resp)
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                last = exc
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Horizons failed after {HORIZONS_RETRIES} attempts: {last}")


def horizons_elevations(body: str, lat: float, lon: float) -> np.ndarray:
    """Hourly apparent elevation (deg) of `body` ('10' Sun, '399' Earth) at a lunar surface point.

    Uses a topocentric site on the Moon (CENTER='coord@301', the Moon-centred
    user-defined-site form of 'c@301') so Horizons applies the lunar rotation model.
    """
    params = {
        "format": "json", "COMMAND": f"'{body}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'coord@301'", "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{lon:.6f},{lat:.6f},0'", "START_TIME": f"'{START_TIME}'",
        "STOP_TIME": f"'{STOP_TIME}'", "STEP_SIZE": f"'{STEP}'", "QUANTITIES": "'4'",
        "ANG_FORMAT": "'DEG'", "APPARENT": "'AIRLESS'", "CSV_FORMAT": "'YES'",
    }
    payload = horizons_get(params)
    if "result" not in payload or "$$SOE" not in payload["result"]:
        raise RuntimeError(f"Horizons error: {str(payload.get('error') or payload.get('result'))[:300]}")
    head, body_txt = payload["result"].split("$$SOE")
    rows = body_txt.split("$$EOE")[0].strip().splitlines()
    header_line = next(ln for ln in reversed(head.splitlines()) if "Elev" in ln)
    header = [h.strip() for h in header_line.split(",")]
    el_idx = next(i for i, h in enumerate(header) if h.startswith("Elev"))
    elev = np.array([float(r.split(",")[el_idx]) for r in rows if r.strip()])
    if elev.size != N_SAMPLES:
        raise RuntimeError(f"Horizons returned {elev.size} samples, expected {N_SAMPLES}")
    return elev


def fetch_live(lat: float, lon: float) -> HourlySeries:
    """Blocking Horizons fetch of Sun and Earth, stored in the cache."""
    series = HourlySeries(horizons_elevations("10", lat, lon), horizons_elevations("399", lat, lon),
                          source="horizons_live")
    save_cache(lat, lon, series)
    return series


# ----------------------------------------------------------------------------
# Cache
# ----------------------------------------------------------------------------
def _key(lat: float, lon: float) -> str:
    return f"{round(lat, CACHE_DECIMALS):+09.3f}_{round(lon % 360.0, CACHE_DECIMALS):07.3f}"


def cache_path(lat: float, lon: float) -> Path:
    return CACHE_DIR / f"{_key(lat, lon)}.npz"


def save_cache(lat: float, lon: float, s: HourlySeries) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    np.savez_compressed(cache_path(lat, lon), sun_el=s.sun_el, earth_el=s.earth_el, lat=lat, lon=lon,
                        fetched_utc=datetime.now(timezone.utc).isoformat())


def load_cache(lat: float, lon: float) -> HourlySeries | None:
    p = cache_path(lat, lon)
    if not p.exists():
        return None
    try:
        with np.load(p) as z:
            return HourlySeries(z["sun_el"].astype(float), z["earth_el"].astype(float), "horizons_cache")
    except Exception:
        return None  # corrupt cache entry: ignore and re-derive


# ----------------------------------------------------------------------------
# Analytic physics model
# ----------------------------------------------------------------------------
def sun_model(lat: float, lon: float, t_h: np.ndarray, p: dict | None = None) -> np.ndarray:
    """Sun elevation (deg): sin(el) = sin(phi) sin(d) + cos(phi) cos(d) cos(lon - lon_subsolar(t)).

    The sub-solar longitude sweeps 360 deg per synodic month; the sub-solar latitude d drifts
    slowly (seasonal, +/-1.54 deg) and is modelled as linear over the 60-day window.
    """
    p = p or MODEL_PARAMS["sun"]
    phi = math.radians(lat)
    d = np.radians(p["d0"] + p["d1"] * (t_h - 720.0) / 720.0)
    lam_ss = p["lam0"] - 360.0 * t_h / P_SYNODIC_H
    s = math.sin(phi) * np.sin(d) + math.cos(phi) * np.cos(d) * np.cos(np.radians(lon - lam_ss))
    return np.degrees(np.arcsin(np.clip(s, -1, 1)))


def earth_model(lat: float, lon: float, t_h: np.ndarray, p: dict | None = None) -> np.ndarray:
    """Earth elevation (deg) from optical libration of the sub-Earth point, with surface parallax.

    sin(el_geo) = sin(phi) sin(b) + cos(phi) cos(b) cos(lon - l), where the sub-Earth
    latitude b and longitude l oscillate about (0, 0); the topocentric elevation is lower
    than the selenocentric one by (R_moon / D_earth) cos(el) (about 0.26 deg).
    """
    p = p or MODEL_PARAMS["earth"]
    phi = math.radians(lat)
    b = np.radians(p["b_amp"] * np.sin(2 * np.pi * t_h / P_DRACONIC_H + p["b_phase"]))
    l = p["l_amp"] * np.sin(2 * np.pi * t_h / P_ANOMALISTIC_H + p["l_phase"])
    s = math.sin(phi) * np.sin(b) + math.cos(phi) * np.cos(b) * np.cos(np.radians(lon - l))
    el_geo = np.arcsin(np.clip(s, -1, 1))
    return np.degrees(el_geo - (R_MOON_KM / EARTH_DISTANCE_KM) * np.cos(el_geo))


def analytic_series(lat: float, lon: float) -> HourlySeries:
    """Uncalibrated analytic series for any (lat, lon)."""
    t = np.arange(N_SAMPLES, dtype=float) * STEP_HOURS
    return HourlySeries(sun_model(lat, lon, t), earth_model(lat, lon, t), "analytic_model",
                        notes=["Analytic physics model (flat horizon); not tied to this site's Horizons data."])


def calibrate_to_stats(el: np.ndarray, vis_pct: float, avg_el: float, max_el: float) -> np.ndarray:
    """Monotone quadratic remap f(s) so that max, mean and visible fraction equal the targets.

    Solves f(s_max) = max_el, mean(f(s)) = avg_el and f(s*) = 0 where s* is the (1 - vis)
    quantile of the samples, giving exactly the requested Visible_Pct (to 1/N). Falls back
    to an affine remap (mean and max only) if the quadratic is not monotone.
    """
    s = np.asarray(el, dtype=float)
    smax, smin = s.max(), s.min()
    ss = np.sort(s)
    n_vis = int(round(vis_pct / 100.0 * s.size))
    if 0 < n_vis < s.size:
        k = s.size - n_vis                      # samples at or below the horizon
        s_star = 0.5 * (ss[k - 1] + ss[k])
        c = np.array([[1, smax, smax**2], [1, s.mean(), (s**2).mean()], [1, s_star, s_star**2]])
        rhs = np.array([max_el, avg_el, 0.0])
    elif n_vis >= s.size:                       # always lit: pin the minimum slightly above horizon
        floor = max(0.05, 2 * avg_el - max_el)
        c = np.array([[1, smax, smax**2], [1, s.mean(), (s**2).mean()], [1, smin, smin**2]])
        rhs = np.array([max_el, avg_el, floor])
    else:                                       # never lit
        c = None
        rhs = None
    if c is not None:
        try:
            a = np.linalg.solve(c, rhs)
            grid = np.linspace(smin, smax, 200)
            if np.all(a[1] + 2 * a[2] * grid > 0):
                return a[0] + a[1] * s + a[2] * s**2
        except np.linalg.LinAlgError:
            pass
    if 0 < n_vis < s.size:
        # Two-segment monotone remap through (s*, 0): still exact in max, mean and visible fraction.
        d = s - s_star
        pos, neg = d >= 0, d < 0
        m_hi = max_el / max(smax - s_star, 1e-9)
        a_pos, b_neg = d[pos].sum() / s.size, d[neg].sum() / s.size
        m_lo = (avg_el - m_hi * a_pos) / b_neg if b_neg < 0 else 0.0
        if m_lo > 0:
            return np.where(pos, m_hi * d, m_lo * d)
    scale = (max_el - avg_el) / max(smax - s.mean(), 1e-9)
    return avg_el + scale * (s - s.mean())


def series_stats(sun_el: np.ndarray, earth_el: np.ndarray) -> dict:
    """Dataset-style window statistics of the two series."""
    return {"Sun_Visible_Pct": float((sun_el > 0).mean() * 100), "Sun_Avg_El": float(sun_el.mean()),
            "Sun_Max_El": float(sun_el.max()), "Earth_Visible_Pct": float((earth_el > 0).mean() * 100),
            "Earth_Avg_El": float(earth_el.mean()), "Earth_Max_El": float(earth_el.max())}


def calibrated_series(lat: float, lon: float, row: dict) -> HourlySeries:
    """Analytic series remapped to a preset site's dataset statistics (exact match)."""
    base = analytic_series(lat, lon)
    sun = calibrate_to_stats(base.sun_el, row["Sun_Visible_Pct"], row["Sun_Avg_El"], row["Sun_Max_El"])
    earth = calibrate_to_stats(base.earth_el, row["Earth_Visible_Pct"], row["Earth_Avg_El"], row["Earth_Max_El"])
    return HourlySeries(sun, earth, "analytic_calibrated", calibrated=True,
                        notes=["Analytic curve calibrated to the dataset's Sun/Earth Visible_Pct, Avg_El and Max_El."])


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------
def _freeze(s: HourlySeries) -> HourlySeries:
    s.sun_el.setflags(write=False)
    s.earth_el.setflags(write=False)
    return s


def get_hourly_series(lat: float, lon: float, site_row: dict | None = None, mode: str = "auto") -> HourlySeries:
    """Hourly Sun/Earth elevation series.

    mode:
      "auto"     cache -> preset: calibrated analytic (instant) -> custom: Horizons with a
                 LIVE_BUDGET_S wait, else analytic now while the fetch completes in the background.
      "live"     cache -> blocking Horizons fetch (raises on failure).
      "analytic" skip cache/network; calibrated if `site_row` is given.
      "cache"    cache only (raises KeyError on a miss).
    """
    lon = lon % 360.0
    mkey = (_key(lat, lon), mode, site_row is not None)
    if mkey in _MEMORY:
        return _MEMORY[mkey]
    series: HourlySeries | None = None
    if mode != "analytic":
        series = load_cache(lat, lon)
    if series is None:
        if mode == "cache":
            raise KeyError("no cached ephemeris for this coordinate")
        if mode == "live":
            series = fetch_live(lat, lon)
        elif mode == "analytic" or site_row is not None:
            series = calibrated_series(lat, lon, site_row) if site_row is not None else analytic_series(lat, lon)
        else:  # auto + custom coordinate: bounded wait for Horizons
            key = _key(lat, lon)
            with _INFLIGHT_LOCK:
                fut = _INFLIGHT.get(key) or _POOL.submit(fetch_live, lat, lon)
                _INFLIGHT[key] = fut
            fut.add_done_callback(lambda _f, k=key: _INFLIGHT.pop(k, None))
            try:
                series = fut.result(timeout=LIVE_BUDGET_S)
            except (FutureTimeout, Exception) as exc:
                series = analytic_series(lat, lon)
                series.notes.append(f"Horizons did not answer within {LIVE_BUDGET_S:g} s ({type(exc).__name__}); "
                                    "analytic curve used, live fetch continues in the background and will be cached.")
                return _freeze(series)  # not memoised: the cache will serve the real data next time
    _MEMORY[mkey] = _freeze(series)
    return series
