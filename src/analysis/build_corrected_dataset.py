"""Build outputs/terrain_corrected_dataset.csv: the 100 sites' Sun/Earth features with real terrain shadowing.

For each site, the hourly Sun/Earth series that reproduces the original dataset (smooth horizon) is measured against the
site's real horizon in the direction of the Sun / Earth each hour (ray-traced from the NASA LOLA DEM, calibrated to NASA's
illumination map; terrain_illumination.correct), and the dataset-style features are recomputed over the same 60-day baseline. Terrain columns are unchanged. final_lunar_dataset_fixed.csv is never modified.

    python src/analysis/build_corrected_dataset.py      (then retrain: python src/analysis/train_and_evaluate.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ephemeris_series as es  # noqa: E402
import horizon as hz  # noqa: E402
import numpy as np  # noqa: E402
import terrain_illumination as ti  # noqa: E402
from suitability import DATA_CSV, TRAINING_CSV  # noqa: E402


def build_profiles(src: pd.DataFrame) -> None:
    """Ray-trace the 100 sites' horizons from the LOLA DEM and fit their NASA calibration offsets (cached npz)."""
    hz.download()
    lat, lon = src["Lat"].to_numpy(float), src["Lon"].to_numpy(float)
    profiles = np.stack([hz.compute_profile(a, b) for a, b in zip(lat, lon)])
    nasa = [ti.nasa_visibility(round(a, 4), round(b % 360, 4)) for a, b in zip(lat, lon)]
    raw = np.array([hz.long_run_visibility(p, a, b) for p, a, b in zip(profiles, lat, lon)])
    offs = np.array([hz.fit_offsets(p, a, b, n["sun_pct"], n["earth_pct"]) for p, a, b, n in zip(profiles, lat, lon, nasa)])
    np.savez_compressed(hz.PROFILES_NPZ, site_id=src["Site_ID"].to_numpy(str), lat=lat, lon=lon, azimuth_deg=hz.AZIMUTHS,
                        profiles=profiles, d_sun=offs[:, 0], d_earth=offs[:, 1], raw_sun_pct=raw[:, 0], raw_earth_pct=raw[:, 1],
                        nasa_sun_pct=[n["sun_pct"] for n in nasa], nasa_earth_pct=[n["earth_pct"] for n in nasa])
    hz._cached_profiles.cache_clear(); hz.profile_for.cache_clear()
    print(f"horizon profiles: {hz.PROFILES_NPZ.name}; calibration offsets sun {np.median(np.abs(offs[:, 0])):.2f} deg "
          f"(median |d|), earth {np.median(np.abs(offs[:, 1])):.2f} deg")


def build() -> pd.DataFrame:
    ti.download()
    if not ti.available():
        raise RuntimeError("NASA LOLA illumination maps missing or incomplete in data/lola_illumination/")
    src = pd.read_csv(DATA_CSV)
    build_profiles(src)
    rows = []
    for _, r in src.iterrows():
        base = es.calibrated_series(float(r["Lat"]), float(r["Lon"]), r.to_dict())  # reproduces the original features
        sun, earth, info = ti.correct(base.sun_el, base.earth_el, float(r["Lat"]), float(r["Lon"]))
        st = es.series_stats(sun, earth)
        rows.append({**r.to_dict(), **{k: round(v, 2) for k, v in st.items()},  # 2 decimals, like the original dataset
                     "Smooth_Sun_Visible_Pct": r["Sun_Visible_Pct"], "Smooth_Earth_Visible_Pct": r["Earth_Visible_Pct"],
                     "NASA_Sun_Pct": info["nasa_sun_visible_pct"], "NASA_Earth_Pct": info["nasa_earth_visible_pct"],
                     "Raytraced_Sun_Pct": info["raytraced_long_run_pct"]["sun"], "Raytraced_Earth_Pct": info["raytraced_long_run_pct"]["earth"],
                     "Sun_Horizon_Deg": info["sun_horizon_deg"], "Earth_Horizon_Deg": info["earth_horizon_deg"]})
    out = pd.DataFrame(rows)
    out.to_csv(TRAINING_CSV, index=False)
    return out


if __name__ == "__main__":
    d = build()
    print(f"wrote {TRAINING_CSV} ({len(d)} sites)")
    print(d[["Sun_Visible_Pct", "NASA_Sun_Pct", "Raytraced_Sun_Pct", "Earth_Visible_Pct", "NASA_Earth_Pct", "Raytraced_Earth_Pct"]].describe().round(2).to_string())
