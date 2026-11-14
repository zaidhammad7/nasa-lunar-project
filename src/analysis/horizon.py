"""Real terrain horizons from the NASA LOLA south-polar elevation model, and Sun/Earth visibility against them.

For a point we cast rays in N_AZ directions over the LOLA DEM (LDEM_75S_120M: 120 m/px, -75..-90 deg) and keep, per
direction, the highest elevation angle of the terrain, using exact 3-D geometry on the sphere (so the Moon's curvature is
included). The Sun / Earth is visible when its elevation exceeds the horizon *in its own direction* - so crater walls,
ridges and distant massifs (e.g. Malapert, ~5 km high) shadow a site only when the Sun is behind them.

Validation (validate_illumination.py) compares the long-run visibility this predicts with NASA's independently computed
illumination maps - an independent check, because the profiles come from terrain only.

DEM: https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_75s_120m.img
(116 MB, git-ignored in data/lola_dem/). Profiles of the 100 dataset sites are cached in outputs/horizon_profiles.npz,
so presets work without the DEM.
"""
from __future__ import annotations

import math
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEM_PATH = ROOT / "data" / "lola_dem" / "ldem_75s_120m.img"
DEM_URL = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_75s_120m.img"
PROFILES_NPZ = ROOT / "outputs" / "horizon_profiles.npz"
N_PIX = 7624
PIX_M = 120.0
CENTER_PIX = 3811.5
DN_TO_M = 0.5                     # height above the 1737.4 km sphere = DN * 0.5 m
R_MOON_M = 1_737_400.0
N_AZ = 720                        # 0.5 deg azimuth resolution (the Sun moves ~0.5 deg of azimuth per hour)
MAX_RANGE_M = 250_000.0           # beyond ~250 km the Moon's curvature hides any polar relief (drop > 18 km)
OBSERVER_HEIGHT_M = 2.0           # lander deck / panel height above ground
SUN_RADIUS_DEG = 0.265
EARTH_RADIUS_DEG = 0.95           # Earth's angular radius seen from the Moon
EARTH_PARALLAX_DEG = math.degrees(1737.4 / 384400.0)
# Long-run geometry (validation against NASA's 2009-2013 averages): physical amplitudes, all phases sampled.
OBLIQUITY_DEG = 1.543             # sub-solar latitude range over a draconic year
DRACONIC_YEAR_H = 346.62 * 24
P_SYNODIC_H = 29.530589 * 24
LIB_LAT_DEG, LIB_LON_DEG = 6.7, 7.9   # optical libration amplitudes
P_DRACONIC_H, P_ANOMALISTIC_H = 27.212221 * 24, 27.554550 * 24
LONG_RUN_YEARS, LONG_RUN_STEP_H = 4.0, 3.0

_DISTS = np.unique(np.concatenate([np.arange(PIX_M, 6000.0, PIX_M / 2), np.geomspace(6000.0, MAX_RANGE_M, 420)]))
AZIMUTHS = np.arange(N_AZ) * (360.0 / N_AZ)


def download() -> Path:
    if not DEM_PATH.exists():
        DEM_PATH.parent.mkdir(parents=True, exist_ok=True)
        print("downloading LOLA LDEM_75S_120M (116 MB) ...")
        urllib.request.urlretrieve(DEM_URL, DEM_PATH)
    return DEM_PATH


@lru_cache(maxsize=1)
def _dem() -> np.memmap | None:
    if not DEM_PATH.exists() or DEM_PATH.stat().st_size != N_PIX * N_PIX * 2:
        return None
    return np.memmap(DEM_PATH, dtype="<i2", mode="r", shape=(N_PIX, N_PIX))


def dem_available() -> bool:
    return _dem() is not None


def _to_pixel(lat, lon):
    """South polar stereographic (PDS LOLA): (line, sample), 0-based, vectorised."""
    rho = 2 * R_MOON_M * np.tan(np.pi / 4 + np.radians(lat) / 2)
    x, y = rho * np.sin(np.radians(lon)), rho * np.cos(np.radians(lon))
    return CENTER_PIX - y / PIX_M, CENTER_PIX + x / PIX_M


def height_m(lat, lon) -> np.ndarray:
    """Bilinear terrain height (m above the reference sphere)."""
    m = _dem()
    line, samp = _to_pixel(np.asarray(lat, float), np.asarray(lon, float))
    i0 = np.clip(np.floor(line).astype(int), 0, N_PIX - 2)
    j0 = np.clip(np.floor(samp).astype(int), 0, N_PIX - 2)
    fi, fj = np.clip(line - i0, 0, 1), np.clip(samp - j0, 0, 1)
    z00, z01 = m[i0, j0].astype(float), m[i0, j0 + 1].astype(float)
    z10, z11 = m[i0 + 1, j0].astype(float), m[i0 + 1, j0 + 1].astype(float)
    return DN_TO_M * ((z00 * (1 - fj) + z01 * fj) * (1 - fi) + (z10 * (1 - fj) + z11 * fj) * fi)


def _unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def compute_profile(lat: float, lon: float, observer_m: float = OBSERVER_HEIGHT_M) -> np.ndarray:
    """Horizon elevation angle (deg) for each of AZIMUTHS (from north, clockwise), exact spherical geometry."""
    if _dem() is None:
        raise RuntimeError(f"LOLA DEM not found at {DEM_PATH}")
    phi1, lam1 = math.radians(lat), math.radians(lon)
    th = np.radians(AZIMUTHS)[:, None]
    dl = (_DISTS / R_MOON_M)[None, :]
    phi2 = np.arcsin(np.sin(phi1) * np.cos(dl) + np.cos(phi1) * np.sin(dl) * np.cos(th))
    lam2 = lam1 + np.arctan2(np.sin(th) * np.sin(dl) * np.cos(phi1), np.cos(dl) - np.sin(phi1) * np.sin(phi2))
    lat2, lon2 = np.degrees(phi2), np.degrees(lam2) % 360.0
    u0 = _unit(lat, lon)
    p0 = (R_MOON_M + float(height_m(lat, lon)) + observer_m) * u0
    p = (R_MOON_M + height_m(lat2, lon2))[..., None] * _unit(lat2, lon2)
    v = p - p0
    el = np.degrees(np.arcsin(np.clip((v @ u0) / np.linalg.norm(v, axis=-1), -1, 1)))
    return el.max(axis=1).astype(np.float32)


def azimuth_to(lat: float, lon: float, sub_lat, sub_lon) -> np.ndarray:
    """Azimuth (deg from north, clockwise) of the body whose sub-point is (sub_lat, sub_lon)."""
    phi, phis = math.radians(lat), np.radians(sub_lat)
    dlon = np.radians(np.asarray(sub_lon) - lon)
    return np.degrees(np.arctan2(np.sin(dlon) * np.cos(phis), np.cos(phi) * np.sin(phis) - np.sin(phi) * np.cos(phis) * np.cos(dlon))) % 360.0


def elevation_from(lat: float, lon: float, sub_lat, sub_lon) -> np.ndarray:
    phi, phis = math.radians(lat), np.radians(sub_lat)
    s = math.sin(phi) * np.sin(phis) + math.cos(phi) * np.cos(phis) * np.cos(np.radians(lon - np.asarray(sub_lon)))
    return np.degrees(np.arcsin(np.clip(s, -1, 1)))


def horizon_at(profile: np.ndarray, az) -> np.ndarray:
    """Profile value at arbitrary azimuths (linear, circular)."""
    x = np.asarray(az) / (360.0 / N_AZ)
    i0 = np.floor(x).astype(int) % N_AZ
    f = x - np.floor(x)
    return profile[i0] * (1 - f) + profile[(i0 + 1) % N_AZ] * f


def baseline_subpoints(t_h: np.ndarray) -> tuple:
    """Sub-solar and sub-Earth points over the 60-day baseline (same model as ephemeris_series)."""
    from ephemeris_series import MODEL_PARAMS, P_ANOMALISTIC_H as PA, P_DRACONIC_H as PD, P_SYNODIC_H as PS
    s, e = MODEL_PARAMS["sun"], MODEL_PARAMS["earth"]
    sun_lat = s["d0"] + s["d1"] * (t_h - 720.0) / 720.0
    sun_lon = s["lam0"] - 360.0 * t_h / PS
    earth_lat = e["b_amp"] * np.sin(2 * np.pi * t_h / PD + e["b_phase"])
    earth_lon = e["l_amp"] * np.sin(2 * np.pi * t_h / PA + e["l_phase"])
    return sun_lat, sun_lon, earth_lat, earth_lon


def _long_run_margins(profile: np.ndarray, lat: float, lon: float) -> tuple[np.ndarray, np.ndarray]:
    """Sun and Earth elevation above the terrain horizon (deg) over LONG_RUN_YEARS, all seasonal/libration phases."""
    t = np.arange(0.0, LONG_RUN_YEARS * 365.25 * 24, LONG_RUN_STEP_H)
    s_lat = OBLIQUITY_DEG * np.sin(2 * np.pi * t / DRACONIC_YEAR_H)
    s_lon = -360.0 * t / P_SYNODIC_H
    e_lat = LIB_LAT_DEG * np.sin(2 * np.pi * t / P_DRACONIC_H)
    e_lon = LIB_LON_DEG * np.sin(2 * np.pi * t / P_ANOMALISTIC_H)
    sun = elevation_from(lat, lon, s_lat, s_lon) - horizon_at(profile, azimuth_to(lat, lon, s_lat, s_lon))
    earth = elevation_from(lat, lon, e_lat, e_lon) - EARTH_PARALLAX_DEG - horizon_at(profile, azimuth_to(lat, lon, e_lat, e_lon))
    return sun, earth


def _disc_pct(margin: np.ndarray, radius: float) -> float:
    return float(np.clip((margin + radius) / (2 * radius), 0, 1).mean() * 100)


def long_run_visibility(profile: np.ndarray, lat: float, lon: float, d_sun: float = 0.0, d_earth: float = 0.0) -> tuple[float, float]:
    """Average visible disc fraction (%) of Sun and Earth over LONG_RUN_YEARS (comparable with NASA's 2009-2013 maps)."""
    sun, earth = _long_run_margins(profile, lat, lon)
    return _disc_pct(sun - d_sun, SUN_RADIUS_DEG), _disc_pct(earth - d_earth, EARTH_RADIUS_DEG)


PERMANENT_MARGIN_DEG = 1.6  # NASA-never-lit / never-seen points stay so in every season and with any mast (see terrain_illumination)


def fit_offsets(profile: np.ndarray, lat: float, lon: float, nasa_sun: float, nasa_earth: float) -> tuple[float, float]:
    """Uniform horizon offsets (deg) so long-run Sun / Earth visibility equal NASA's values (bisection, monotone)."""
    sun, earth = _long_run_margins(profile, lat, lon)
    out = []
    for m, r, target in ((sun, SUN_RADIUS_DEG, nasa_sun), (earth, EARTH_RADIUS_DEG, nasa_earth)):
        lo, hi = -6.0, 6.0
        for _ in range(32):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _disc_pct(m - mid, r) > target else (lo, mid)
        d = (lo + hi) / 2
        if target <= 0.05:
            d += PERMANENT_MARGIN_DEG
        elif target >= 99.95:
            d -= PERMANENT_MARGIN_DEG
        out.append(d)
    return out[0], out[1]


@lru_cache(maxsize=1)
def _cached_profiles() -> dict:
    if not PROFILES_NPZ.exists():
        return {}
    z = np.load(PROFILES_NPZ)
    return {(round(float(a), 4), round(float(b), 4)): (z["profiles"][k], float(z["d_sun"][k]), float(z["d_earth"][k]))
            for k, (a, b) in enumerate(zip(z["lat"], z["lon"]))}


@lru_cache(maxsize=2048)
def profile_for(lat: float, lon: float) -> np.ndarray | None:
    """Horizon profile for a point: cached preset, else computed from the DEM, else None."""
    hit = _cached_profiles().get((round(lat, 4), round(lon % 360.0, 4)))
    if hit is not None:
        return hit[0]
    if not dem_available():
        return None
    return compute_profile(lat, lon)


def mast_observer_m(tower_m: float) -> float:
    """Height (m) the panels / antenna see from: the top of the mast, never below the lander deck."""
    return max(float(tower_m), OBSERVER_HEIGHT_M)


@lru_cache(maxsize=4096)
def profile_at_height(lat: float, lon: float, observer_m: float) -> np.ndarray | None:
    """Horizon profile seen from observer_m above the ground (deg, N_AZ directions); None without terrain data.

    Raising the observer lowers the elevation angle of every terrain point, so the horizon - and therefore any loss of
    Sun / Earth - can only shrink as the mast grows. Nearby crater walls are cleared by angle atan(h / distance), which a
    uniform curvature dip would miss (it under-states a tall mast next to a wall by tens of percentage points of sunlight).
    """
    if abs(observer_m - OBSERVER_HEIGHT_M) < 1e-9:
        return profile_for(lat, lon)
    if not dem_available():
        return None
    return compute_profile(lat, lon, observer_m)


def cached_offsets(lat: float, lon: float) -> tuple[float, float] | None:
    hit = _cached_profiles().get((round(lat, 4), round(lon % 360.0, 4)))
    return None if hit is None else (hit[1], hit[2])
