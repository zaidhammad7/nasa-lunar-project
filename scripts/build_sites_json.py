"""Regenerate frontend/src/api/sitesData.json (the app's offline copy of the 100 scored sites) from
outputs/ranked_lunar_sites.csv and outputs/site_roughness.csv.  Run after retraining:

    python scripts/build_sites_json.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
rk = pd.read_csv(ROOT / "outputs" / "ranked_lunar_sites.csv")
rough = pd.read_csv(ROOT / "outputs" / "site_roughness.csv").set_index("Site_ID")["Roughness_m"]
sites = [{
    "id": r.Site_ID, "lat": round(r.Lat, 4), "lon": round(r.Lon, 4),
    "sun": round(r.Sun_Visible_Pct, 2), "sunAvg": round(r.Sun_Avg_El, 2), "sunMax": round(r.Sun_Max_El, 2),
    "earth": round(r.Earth_Visible_Pct, 2), "earthAvg": round(r.Earth_Avg_El, 2), "earthMax": round(r.Earth_Max_El, 2),
    "elev": round(r.Elevation_m, 1), "slope": round(r.Slope_deg, 3), "rough": round(float(rough[r.Site_ID]), 3),
    "ruleClass": r.Safety_Class, "ruleScore": round(r.Suitability_Score, 3), "rank": int(r.Rank),
} for r in rk.sort_values("Site_ID").itertuples()]
out = ROOT / "frontend" / "src" / "api" / "sitesData.json"
out.write_text(json.dumps(sites, separators=(",", ":")), encoding="utf-8")
print(f"wrote {out} ({len(sites)} sites)")
