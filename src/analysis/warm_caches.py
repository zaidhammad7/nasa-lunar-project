"""Pre-compute caches so the API answers instantly.

    python src/analysis/warm_caches.py                  # roughness for the 100 preset sites (LOLA DEM)
    python src/analysis/warm_caches.py --ephemeris 10   # also fetch real Horizons series for 10 sites (~14 s each)

Outputs
  outputs/site_roughness.csv   Site_ID, Lat, Lon, Elevation_m, Slope_deg, Roughness_m  (from the 3x3 DEM window)
  ephemeris_cache/*.npz        real hourly Sun/Earth series (git-ignored, regenerable)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ephemeris_series as es  # noqa: E402
import predict_site as ps  # noqa: E402
from suitability import DATA_CSV, OUTPUTS_DIR  # noqa: E402


def build_roughness() -> pd.DataFrame:
    """Sample the LOLA DEM at every preset site; also re-checks Elevation/Slope against the CSV."""
    df = pd.read_csv(DATA_CSV)
    rows = []
    for _, r in df.iterrows():
        t = ps.get_terrain_metrics(float(r["Lat"]), float(r["Lon"]))
        rows.append({"Site_ID": r["Site_ID"], "Lat": r["Lat"], "Lon": r["Lon"], "Elevation_m": t["Elevation_m"],
                     "Slope_deg": t["Slope_deg"], "Roughness_m": t["Roughness_m"],
                     "csv_elevation_diff_m": t["Elevation_m"] - r["Elevation_m"],
                     "csv_slope_diff_deg": t["Slope_deg"] - r["Slope_deg"]})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ephemeris", type=int, default=0, help="fetch real Horizons series for the first N preset sites")
    ap.add_argument("--sites", nargs="*", default=[], help="specific Site_IDs to fetch from Horizons")
    a = ap.parse_args()
    OUTPUTS_DIR.mkdir(exist_ok=True)
    out = build_roughness()
    out.to_csv(OUTPUTS_DIR / "site_roughness.csv", index=False)
    print(f"roughness: {len(out)} sites; max |elev diff| {out.csv_elevation_diff_m.abs().max():.3f} m, "
          f"max |slope diff| {out.csv_slope_diff_deg.abs().max():.4f} deg; "
          f"Roughness_m range {out.Roughness_m.min():.2f}..{out.Roughness_m.max():.2f}", flush=True)
    df = pd.read_csv(DATA_CSV).set_index("Site_ID")
    ids = list(a.sites) + list(df.index[: a.ephemeris])
    for sid in ids:
        r = df.loc[sid]
        if es.load_cache(r.Lat, r.Lon) is None:
            es.fetch_live(float(r.Lat), float(r.Lon))
            print("cached real ephemeris:", sid, flush=True)


if __name__ == "__main__":
    main()
