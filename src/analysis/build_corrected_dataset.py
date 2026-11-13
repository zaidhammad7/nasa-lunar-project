"""Build outputs/terrain_corrected_dataset.csv: the 100 sites' Sun/Earth features with real terrain shadowing.

For each site, the hourly Sun/Earth series that reproduces the original dataset (smooth horizon) is shifted by the
site's effective horizon from NASA LOLA (terrain_illumination.correct), and the dataset-style features are recomputed
over the same 60-day baseline. Terrain columns are unchanged. final_lunar_dataset_fixed.csv is never modified.

    python src/analysis/build_corrected_dataset.py      (then retrain: python src/analysis/train_and_evaluate.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ephemeris_series as es  # noqa: E402
import terrain_illumination as ti  # noqa: E402
from suitability import DATA_CSV, TRAINING_CSV  # noqa: E402


def build() -> pd.DataFrame:
    ti.download()
    if not ti.available():
        raise RuntimeError("NASA LOLA illumination maps missing or incomplete in data/lola_illumination/")
    src = pd.read_csv(DATA_CSV)
    rows = []
    for _, r in src.iterrows():
        base = es.calibrated_series(float(r["Lat"]), float(r["Lon"]), r.to_dict())  # reproduces the original features
        sun, earth, info = ti.correct(base.sun_el, base.earth_el, float(r["Lat"]), float(r["Lon"]))
        st = es.series_stats(sun, earth)
        rows.append({**r.to_dict(), **{k: round(v, 2) for k, v in st.items()},  # 2 decimals, like the original dataset
                     "Smooth_Sun_Visible_Pct": r["Sun_Visible_Pct"], "Smooth_Earth_Visible_Pct": r["Earth_Visible_Pct"],
                     "NASA_Sun_Pct": info["nasa_sun_visible_pct"], "NASA_Earth_Pct": info["nasa_earth_visible_pct"],
                     "Sun_Horizon_Deg": info["sun_horizon_deg"], "Earth_Horizon_Deg": info["earth_horizon_deg"]})
    out = pd.DataFrame(rows)
    out.to_csv(TRAINING_CSV, index=False)
    return out


if __name__ == "__main__":
    d = build()
    print(f"wrote {TRAINING_CSV} ({len(d)} sites)")
    print(d[["Sun_Visible_Pct", "NASA_Sun_Pct", "Earth_Visible_Pct", "NASA_Earth_Pct", "Sun_Horizon_Deg", "Earth_Horizon_Deg"]].describe().round(2).to_string())
