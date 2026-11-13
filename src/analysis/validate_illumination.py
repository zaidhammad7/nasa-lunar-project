"""Validate our Sun / Earth visibility against NASA LRO LOLA terrain-shadowed illumination maps.

Reference data (NASA PDS Geosciences Node, LOLA team; Mazarico et al. 2011 method, 2016 release):
Before the fix our smooth-horizon features over-estimated sunlight by ~45 points; the app now applies NASA's terrain
shadowing (terrain_illumination.py), and this script reports both the original gap and the corrected agreement.

  AVGVISIB_85S_060M_201608.IMG        average visible fraction of the solar disc, 2009-07 .. 2013-07
  AVGVISIB_85S_060M_201608_EARTH.IMG  average visible fraction of the Earth disc, same period
  60 m/px polar stereographic, centre -90 deg, INT16, value = DN * 0.00004 (0 = permanent shadow).
  https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/extras/illumination/

Unlike our model (smooth horizon, 60-day window), these maps include shadowing by real crater walls and
mountains, averaged over ~4 years. Raw files (~100 MB) go to data/lola_illumination/ (git-ignored).

    python src/analysis/validate_illumination.py

Writes outputs/illumination_validation.json, outputs/illumination_validation.csv, outputs/illumination_validation.png.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import terrain_illumination as ti  # noqa: E402  (map reading + projection shared with the live scoring)
from suitability import TRAINING_CSV  # noqa: E402

ROOT = ti.ROOT
OUT = ROOT / "outputs"
SHADOWED_LIMIT_PCT = 20.0  # "mostly shadowed" in reality
# Known permanently shadowed crater centres (IAU) used to verify the map orientation before any comparison.
PSR_CHECK = {"Shackleton": (-89.67, 129.78), "de Gerlache": (-88.5, 272.9), "Faustini": (-87.3, 77.0),
             "Haworth": (-86.9, 356.0), "Shoemaker": (-88.1, 44.9), "Sverdrup": (-88.5, 208.0)}
sample_pct = ti.sample_pct


def solar_score(vis, max_el):
    return 0.7 * np.clip(vis, 0, 100) + 0.3 * np.clip(np.asarray(max_el) / 7, 0, 1) * 100


def comms_score(vis, avg_el):
    return 0.7 * np.clip(vis, 0, 100) + 0.3 * np.clip((np.asarray(avg_el) + 6) / 10, 0, 1) * 100


def run() -> dict:
    ti.download()
    sun_m, earth_m = ti._map("sun"), ti._map("earth")

    # 1. Orientation check: every known permanently shadowed crater must read ~0 % sunlight.
    psr = {k: round(sample_pct(sun_m, *v, half=1), 2) for k, v in PSR_CHECK.items()}
    if max(psr.values()) > 1.0:
        raise RuntimeError(f"map orientation check failed (shadowed craters not dark): {psr}")

    # 2. Compare at the 100 sites.
    ds = pd.read_csv(ROOT / "final_lunar_dataset_fixed.csv")
    rk = pd.read_csv(OUT / "ranked_lunar_sites.csv").set_index("Site_ID")
    ds["NASA_Sun_Pct"] = [sample_pct(sun_m, a, b) for a, b in zip(ds["Lat"], ds["Lon"])]
    ds["NASA_Earth_Pct"] = [sample_pct(earth_m, a, b) for a, b in zip(ds["Lat"], ds["Lon"])]
    ds["Sun_Diff"] = ds["Sun_Visible_Pct"] - ds["NASA_Sun_Pct"]
    ds["Earth_Diff"] = ds["Earth_Visible_Pct"] - ds["NASA_Earth_Pct"]

    # 3. What happens to the ranking if the real (terrain-shadowed) visibility is used instead?
    terrain = rk.loc[ds["Site_ID"], "Terrain_Score"].to_numpy()
    ds["Our_Score"] = rk.loc[ds["Site_ID"], "Suitability_Score"].to_numpy()
    ds["NASA_Corrected_Score"] = (0.40 * terrain + 0.35 * solar_score(ds["NASA_Sun_Pct"], ds["Sun_Max_El"])
                                  + 0.25 * comms_score(ds["NASA_Earth_Pct"], ds["Earth_Avg_El"]))
    ds["Our_Rank"] = ds["Our_Score"].rank(ascending=False, method="first").astype(int)
    ds["NASA_Corrected_Rank"] = ds["NASA_Corrected_Score"].rank(ascending=False, method="first").astype(int)

    def stats(ours, nasa):
        d = ours - nasa
        return {"mean_ours_pct": round(float(ours.mean()), 2), "mean_nasa_pct": round(float(nasa.mean()), 2),
                "bias_pct_points": round(float(d.mean()), 2), "mae_pct_points": round(float(d.abs().mean()), 2),
                "rmse_pct_points": round(float(np.sqrt((d ** 2).mean())), 2),
                "pearson_r": round(float(np.corrcoef(ours, nasa)[0, 1]), 3),
                "spearman_rho": round(float(ours.rank().corr(nasa.rank())), 3),
                "within_10_points": int((d.abs() <= 10).sum())}

    # Independent test: horizons ray-traced from the LOLA elevation model ONLY (no NASA illumination input),
    # long-run Sun / Earth visibility vs NASA's map. Then the calibrated result the app scores with.
    after, independent = None, None
    import horizon as hz
    if hz.PROFILES_NPZ.exists():
        z = np.load(hz.PROFILES_NPZ)
        order = pd.Series(range(len(z["site_id"])), index=z["site_id"]).loc[ds["Site_ID"]].to_numpy()
        rs, re_ = pd.Series(z["raw_sun_pct"][order]), pd.Series(z["raw_earth_pct"][order])
        cal = np.array([hz.long_run_visibility(z["profiles"][k], z["lat"][k], z["lon"][k], z["d_sun"][k], z["d_earth"][k]) for k in order])
        ds["Raytraced_Sun_Pct"], ds["Raytraced_Earth_Pct"] = rs.to_numpy(), re_.to_numpy()
        independent = {"sun": stats(rs, ds["NASA_Sun_Pct"]), "earth": stats(re_, ds["NASA_Earth_Pct"]),
                       "note": "Horizons ray-traced from NASA LOLA LDEM_75S_120M only; NASA's illumination map is not used. "
                               "Long-run (4-year, all seasons) visibility compared with NASA's 2009-2013 average."}
        after = {"sun": stats(pd.Series(cal[:, 0]), ds["NASA_Sun_Pct"]), "earth": stats(pd.Series(cal[:, 1]), ds["NASA_Earth_Pct"]),
                 "median_abs_offset_deg": {"sun": round(float(np.median(np.abs(z["d_sun"]))), 3), "earth": round(float(np.median(np.abs(z["d_earth"]))), 3)},
                 "note": "After a small uniform offset per site (fitted to NASA) the long-run averages match by construction; "
                         "the mission-window values then differ from the 4-year average because of the season (Nov-Jan is South-Pole summer)."}

    top_ours = set(ds.nsmallest(10, "Our_Rank")["Site_ID"])
    top_nasa = set(ds.nsmallest(10, "NASA_Corrected_Rank")["Site_ID"])
    best = ds.loc[ds["Our_Rank"].idxmin()]
    report = {
        "reference": "NASA PDS LOLA AVGVISIB_85S_060M_201608 (+ _EARTH), terrain-shadowed, 2009-2013 average",
        "orientation_check_psr_sun_pct": psr,
        "n_sites": int(len(ds)), "sample_box_m": int((2 * ti.WINDOW_PX + 1) * ti.PIX_M),
        "before_fix_smooth_horizon": {"sun": stats(ds["Sun_Visible_Pct"], ds["NASA_Sun_Pct"]),
                                      "earth": stats(ds["Earth_Visible_Pct"], ds["NASA_Earth_Pct"])},
        "independent_raytraced_horizon": independent,
        "after_fix_terrain_shadowed": after,
        "sun": stats(ds["Sun_Visible_Pct"], ds["NASA_Sun_Pct"]),
        "earth": stats(ds["Earth_Visible_Pct"], ds["NASA_Earth_Pct"]),
        "sites_mostly_shadowed_in_reality": int((ds["NASA_Sun_Pct"] < SHADOWED_LIMIT_PCT).sum()),
        "sites_we_rate_50pct_sun_but_reality_below_20": int(((ds["Sun_Visible_Pct"] >= 50) & (ds["NASA_Sun_Pct"] < SHADOWED_LIMIT_PCT)).sum()),
        "ranking_spearman_ours_vs_nasa_corrected": round(float(ds["Our_Rank"].corr(ds["NASA_Corrected_Rank"], method="spearman")), 3),
        "top10_overlap": len(top_ours & top_nasa),
        "our_best_site": {"id": best["Site_ID"], "our_sun_pct": round(float(best["Sun_Visible_Pct"]), 1),
                          "nasa_sun_pct": round(float(best["NASA_Sun_Pct"]), 1), "our_earth_pct": round(float(best["Earth_Visible_Pct"]), 1),
                          "nasa_earth_pct": round(float(best["NASA_Earth_Pct"]), 1), "nasa_corrected_rank": int(best["NASA_Corrected_Rank"])},
        "best_sites_by_nasa_illumination": ds.nsmallest(5, "NASA_Corrected_Rank")[["Site_ID", "NASA_Sun_Pct", "NASA_Earth_Pct", "Slope_deg", "NASA_Corrected_Score", "Our_Rank"]]
            .round(2).to_dict(orient="records"),
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "illumination_validation.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    ds.round(3).to_csv(OUT / "illumination_validation.csv", index=False)
    _plot(ds, report)
    return report


def _plot(ds: pd.DataFrame, rep: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = [("before_fix_smooth_horizon", "Sun_Visible_Pct", "Earth_Visible_Pct", "Before: smooth horizon")]
    if "Raytraced_Sun_Pct" in ds:
        rows.append(("independent_raytraced_horizon", "Raytraced_Sun_Pct", "Raytraced_Earth_Pct", "Now: horizon ray-traced from LOLA terrain"))
    fig, axes = plt.subplots(len(rows), 2, figsize=(11, 4.6 * len(rows)), squeeze=False)
    for r, (key, sun_col, earth_col, label) in enumerate(rows):
        for c, (col, nasa, name) in enumerate([(sun_col, "NASA_Sun_Pct", "sunlight"), (earth_col, "NASA_Earth_Pct", "Earth visibility")]):
            ax = axes[r][c]
            ax.scatter(ds[nasa], ds[col], s=18, alpha=0.75, color="#d62728" if r == 0 else "#1f77b4")
            ax.plot([0, 100], [0, 100], "k--", lw=1, label="perfect agreement")
            st = rep[key]["sun" if c == 0 else "earth"]
            ax.set(xlim=(0, 100), ylim=(0, 100), xlabel=f"NASA LOLA measured {name} (%)", ylabel=f"Model {name} (%)",
                   title=f"{label}\n{name}: MAE {st['mae_pct_points']:.1f} pts, r = {st['pearson_r']:.2f}")
            ax.legend(loc="lower right"); ax.grid(alpha=0.3)
    fig.suptitle("100 South Pole sites vs NASA LRO LOLA terrain-shadowed illumination (2009-2013)", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "illumination_validation.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: r[k] for k in ("orientation_check_psr_sun_pct", "before_fix_smooth_horizon", "independent_raytraced_horizon", "after_fix_terrain_shadowed", "sites_mostly_shadowed_in_reality",
                                         "sites_we_rate_50pct_sun_but_reality_below_20", "ranking_spearman_ours_vs_nasa_corrected",
                                         "top10_overlap", "our_best_site", "best_sites_by_nasa_illumination")}, indent=1))
