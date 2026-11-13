"""Terrain-shadowed illumination from NASA LRO LOLA average-visibility maps.

Our hourly Sun/Earth elevations assume a smooth horizon, so they ignore shadowing by crater walls and mountains -
the dominant effect at the lunar South Pole (validation: sunlight was over-estimated by ~45 points). NASA's LOLA team
publishes, for every 60 m pixel down to -85 deg, the average visible fraction of the Sun and Earth discs computed with the
real terrain (2009-2013 average; PDS AVGVISIB_85S_060M_201608 and ..._EARTH).

Correction used here ("effective horizon"): for each point we find the single horizon elevation h (deg) such that the
fraction of baseline hours with (elevation - h) > 0 equals NASA's measured average visibility; all hourly elevations are
then measured above h. The long-run averages therefore match NASA exactly, and power, darkness spells, countdowns and
features follow consistently. Limitation: h is the same in every azimuth (no full horizon profile), so the timing of
individual sunrises/sunsets is approximate even though the averages are right.

Raw maps (~100 MB) live in data/lola_illumination/ (git-ignored); fetch with  python src/analysis/validate_illumination.py
If they are missing, every function falls back to the smooth horizon (h = 0) and says so.
"""
from __future__ import annotations

import math
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "lola_illumination"
BASE_URL = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/extras/illumination/img/"
FILES = {"sun": "avgvisib_85s_060m_201608.img", "earth": "avgvisib_85s_060m_201608_earth.img"}
N_PIX = 5058              # lines = samples
PIX_M = 60.0              # m / pixel
CENTER_PIX = 2528.5       # LINE/SAMPLE_PROJECTION_OFFSET (pole)
DN_SCALE = 0.00004        # visible fraction = DN * scale
R_MOON_M = 1_737_400.0
WINDOW_PX = 1             # average a 3x3 px (180 m) box around the point
# A point NASA records as never lit (or never seen from Earth) over 4 years must stay so in every season and with any mast:
# the Sun climbs up to the lunar obliquity (1.54 deg) higher than in our 60-day window, and a 150 m mast adds 0.75 deg.
PERMANENT_MARGIN_DEG = 1.6
SOURCE = "NASA LRO LOLA terrain-shadowed average visibility (PDS AVGVISIB_85S_060M_201608, 2009-2013)"


def download() -> dict[str, Path]:
    """Fetch the two maps once into data/lola_illumination/ (51 MB each)."""
    RAW.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, name in FILES.items():
        p = RAW / name
        if not p.exists():
            print(f"downloading {name} (51 MB) ...")
            urllib.request.urlretrieve(BASE_URL + name, p)
        out[key] = p
    return out


@lru_cache(maxsize=2)
def _map(key: str) -> np.memmap | None:
    p = RAW / FILES[key]
    if not p.exists() or p.stat().st_size != N_PIX * N_PIX * 2:
        return None
    return np.memmap(p, dtype="<i2", mode="r", shape=(N_PIX, N_PIX))


def available() -> bool:
    return _map("sun") is not None and _map("earth") is not None


def latlon_to_pixel(lat: float, lon: float) -> tuple[float, float]:
    """South polar stereographic (PDS LOLA convention) -> (line, sample), 0-based, fractional."""
    rho = 2 * R_MOON_M * math.tan(math.pi / 4 + math.radians(lat) / 2)
    x, y = rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))
    return CENTER_PIX - y / PIX_M, CENTER_PIX + x / PIX_M


def sample_pct(m: np.memmap, lat: float, lon: float, half: int = WINDOW_PX) -> float | None:
    """Mean visible fraction (%) in a (2*half+1)^2 px box, or None outside the map."""
    line, samp = latlon_to_pixel(lat, lon)
    i, j = int(round(line)), int(round(samp))
    if not (half <= i < N_PIX - half and half <= j < N_PIX - half):
        return None
    box = np.asarray(m[i - half:i + half + 1, j - half:j + half + 1], dtype=float)
    return float(box.mean() * DN_SCALE * 100)


@lru_cache(maxsize=4096)
def nasa_visibility(lat: float, lon: float) -> dict | None:
    """{'sun_pct', 'earth_pct'} measured by NASA at (lat, lon), or None if the maps are missing / point outside."""
    sm, em = _map("sun"), _map("earth")
    if sm is None or em is None:
        return None
    s, e = sample_pct(sm, lat, lon), sample_pct(em, lat, lon)
    if s is None or e is None:
        return None
    return {"sun_pct": s, "earth_pct": e}


def horizon_for(el: np.ndarray, visible_pct: float) -> float:
    """Effective horizon elevation (deg): the fraction of samples with el > h equals visible_pct."""
    el = np.asarray(el, dtype=float)
    p = min(max(visible_pct, 0.0), 100.0) / 100.0
    if p <= 0.0:  # never seen in NASA's 4-year record: permanent shadow / no line of sight
        return float(el.max() + PERMANENT_MARGIN_DEG)
    if p >= 1.0:  # always seen
        return float(min(el.min() - PERMANENT_MARGIN_DEG, 0.0))
    return float(np.quantile(el, 1.0 - p))


def correct(sun_el: np.ndarray, earth_el: np.ndarray, lat: float, lon: float) -> tuple[np.ndarray, np.ndarray, dict]:
    """Hourly Sun / Earth elevations measured above the real terrain horizon (deg), plus provenance info.

    Priority: (1) direction-dependent horizon ray-traced from the LOLA DEM (horizon.py), with a small uniform offset so the
    long-run average equals NASA's map; (2) a single NASA-fitted effective horizon; (3) the smooth horizon (h = 0).
    """
    import horizon as hz  # local import: horizon imports ephemeris_series lazily
    lat, lon = round(float(lat), 4), round(float(lon) % 360.0, 4)
    v = nasa_visibility(lat, lon)
    prof = hz.profile_for(lat, lon)
    if prof is not None:
        t = np.arange(len(sun_el), dtype=float)
        s_lat, s_lon, e_lat, e_lon = hz.baseline_subpoints(t)
        h_sun = hz.horizon_at(prof, hz.azimuth_to(lat, lon, s_lat, s_lon))
        h_earth = hz.horizon_at(prof, hz.azimuth_to(lat, lon, e_lat, e_lon))
        offs = hz.cached_offsets(lat, lon) or (_fit_offsets(prof, lat, lon, v["sun_pct"], v["earth_pct"]) if v else (0.0, 0.0))
        raw = hz.long_run_visibility(prof, lat, lon)
        info = {"terrain_shadowing": True, "method": "horizon profile ray-traced from NASA LOLA DEM (720 directions)",
                "sun_horizon_deg": round(float(np.mean(h_sun) + offs[0]), 4), "earth_horizon_deg": round(float(np.mean(h_earth) + offs[1]), 4),
                "horizon_min_max_deg": [round(float(prof.min()), 2), round(float(prof.max()), 2)],
                "calibration_offset_deg": {"sun": round(offs[0], 3), "earth": round(offs[1], 3)},
                "raytraced_long_run_pct": {"sun": round(raw[0], 2), "earth": round(raw[1], 2)},
                "source": "NASA LOLA LDEM_75S_120M terrain horizon" + (" + " + SOURCE if v else "")}
        if v:
            info.update(nasa_sun_visible_pct=round(v["sun_pct"], 2), nasa_earth_visible_pct=round(v["earth_pct"], 2))
        return np.asarray(sun_el) - h_sun - offs[0], np.asarray(earth_el) - h_earth - offs[1], info
    if v is None:
        return np.asarray(sun_el), np.asarray(earth_el), {
            "terrain_shadowing": False, "method": "smooth horizon", "sun_horizon_deg": 0.0, "earth_horizon_deg": 0.0,
            "source": "smooth horizon (NASA LOLA data not available)"}
    hs, he = horizon_for(sun_el, v["sun_pct"]), horizon_for(earth_el, v["earth_pct"])
    return np.asarray(sun_el) - hs, np.asarray(earth_el) - he, {
        "terrain_shadowing": True, "method": "single effective horizon fitted to NASA illumination map",
        "sun_horizon_deg": round(hs, 4), "earth_horizon_deg": round(he, 4),
        "nasa_sun_visible_pct": round(v["sun_pct"], 2), "nasa_earth_visible_pct": round(v["earth_pct"], 2), "source": SOURCE}


@lru_cache(maxsize=2048)
def _fit_offsets_cached(lat: float, lon: float, nasa_sun: float, nasa_earth: float) -> tuple[float, float]:
    import horizon as hz
    return hz.fit_offsets(hz.profile_for(lat, lon), lat, lon, nasa_sun, nasa_earth)


def _fit_offsets(prof, lat, lon, nasa_sun, nasa_earth) -> tuple[float, float]:
    return _fit_offsets_cached(lat, lon, round(nasa_sun, 3), round(nasa_earth, 3))
