"""4-part engineering stress test of the hybrid physics-ML landing-site engine.

    python src/analysis/stress_test.py

Panels
  1. Adversarial & boundary trap matrix (7 extreme cases, before vs after the physics guardrails)
  2. Monte Carlo sensor-noise perturbation (1,000 runs x 100 sites x 3 noise levels = 300,000 evaluations)
  3. Physical monotonicity (score vs slope) and solar-hardware sensitivity (power vs tilt / tower height)
  4. Surrogate throughput benchmark (10,000 candidate sites)

Outputs: outputs/stress_test_results.json, outputs/stress_test_dashboard.png (300 DPI).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.gridspec import GridSpec

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402
from suitability import FEATURES, OUTPUTS_DIR, add_labels  # noqa: E402
from train_and_evaluate import find_text_overlaps  # noqa: E402

SEED = 42
N_RUNS = 1000
NOISE_LEVELS = [  # 1-sigma Gaussian noise (slope deg, elevation m, Sun visibility percentage points)
    {"name": "low", "slope_deg": 0.5, "elevation_m": 1.0, "solar_pct": 0.5},
    {"name": "medium", "slope_deg": 1.0, "elevation_m": 2.0, "solar_pct": 1.0},
    {"name": "high", "slope_deg": 2.0, "elevation_m": 5.0, "solar_pct": 2.0},
]
BENCH_SITES = 10_000
MONOTONE_TOL_PTS = 0.5
CLASS_COLORS = {"Optimal": "#2ca02c", "Acceptable": "#ff9f1c", "Hazardous": "#d62728"}

# A healthy mid-quality site used as the template for adversarial cases.
IDEAL = {"Sun_Visible_Pct": 95.0, "Sun_Avg_El": 1.3, "Sun_Max_El": 6.0, "Earth_Visible_Pct": 75.0,
         "Earth_Avg_El": 4.0, "Earth_Max_El": 10.8, "Elevation_m": 0.0, "Slope_deg": 2.0}


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{**IDEAL, **r} for r in rows])[FEATURES]


def truth_labels(df: pd.DataFrame) -> pd.Series:
    """Rule-based (ground-truth) Safety_Class for a feature frame."""
    return add_labels(df)["Safety_Class"]


# ----------------------------------------------------------------------------
# Panel 1
# ----------------------------------------------------------------------------
def panel1() -> dict:
    cases = [
        ("1 Ideal site", {}, "Optimal"),
        ("2 Steep rim 24 deg, 100% Sun trap", {"Slope_deg": 24.0, "Sun_Visible_Pct": 100.0, "Sun_Max_El": 2.5}, "Hazardous"),
        ("3 PSR crater floor, 0% Sun", {"Slope_deg": 3.0, "Sun_Visible_Pct": 0.0, "Sun_Avg_El": -2.5, "Sun_Max_El": -0.2}, "Hazardous"),
        ("4a Boundary 4.8 deg", {"Slope_deg": 4.8}, None),
        ("4b Boundary 5.3 deg", {"Slope_deg": 5.3}, None),
        # with the 1.5 deg safety margin the operational cliff is 13.5 deg, so 14.5 deg is already NO-GO
        ("5a Tip-over cliff 14.5 deg", {"Slope_deg": 14.5}, "Hazardous"),
        ("5b Tip-over cliff 15.6 deg", {"Slope_deg": 15.6}, "Hazardous"),
    ]
    df = _frame([c[1] for c in cases])
    out = ps.predict_batch(df)
    pre = ps.predict_batch(df, safety_factor=False)
    truth = truth_labels(df)
    rows = []
    for i, (name, _, expect) in enumerate(cases):
        exp = expect or str(truth.iloc[i])
        final_cls, final_score = str(out["Safety_Class"].iloc[i]), float(out["Suitability_Score"].iloc[i])
        rows.append({"case": name, "slope_deg": float(df["Slope_deg"].iloc[i]), "sun_pct": float(df["Sun_Visible_Pct"].iloc[i]),
                     "ml_only_class": str(out["class_raw"].iloc[i]), "ml_only_score": round(float(out["score_raw"].iloc[i]), 2),
                     "before_safety_factor_class": str(pre["Safety_Class"].iloc[i]),
                     "guardrailed_class": final_cls, "guardrailed_score": round(final_score, 2),
                     "guardrails_triggered": [c for c in ("TIP_OVER", "PSR", "DTE_BLACKOUT") if bool(out[f"guard_{c}"].iloc[i])],
                     "safety_layers_triggered": [c for c in ps.SAFETY_LAYERS if bool(out[f"safety_{c}"].iloc[i])],
                     "rule_truth_class": str(truth.iloc[i]), "expected_class": exp, "pass": final_cls == exp})
    near = ps.predict_batch(_frame([{"Slope_deg": 13.0}]))
    checks = {
        "steep_rim_score_capped_le_35": rows[1]["guardrailed_score"] <= 35.0,
        "psr_score_capped_le_30": rows[2]["guardrailed_score"] <= 30.0,
        "cliff_15_6_score_capped_le_35": rows[6]["guardrailed_score"] <= 35.0,
        "ideal_score_ge_65": rows[0]["guardrailed_score"] >= 65.0,
        "guardrails_changed_ml_verdict_on_traps": bool(rows[1]["ml_only_class"] != "Hazardous" or rows[2]["ml_only_class"] != "Hazardous"),
        "safety_factor_flags_14_5_deg_but_rule_says_acceptable": bool(
            rows[5]["before_safety_factor_class"] == "Acceptable" and rows[5]["guardrailed_class"] == "Hazardous"
            and "SLOPE_DERATING" in rows[5]["safety_layers_triggered"]),
        "13_0_deg_not_over_derated": str(near["Safety_Class"].iloc[0]) != "Hazardous",
    }
    return {"cases": rows, "extra_checks": checks, "all_pass": all(r["pass"] for r in rows) and all(checks.values())}


# ----------------------------------------------------------------------------
# Panel 2
# ----------------------------------------------------------------------------
def _mc_metrics(out: pd.DataFrame, base_cls: np.ndarray, base_score: np.ndarray, truth: np.ndarray, reps: np.ndarray) -> dict:
    cls_n, cls_b, tr = out["Safety_Class"].to_numpy(), base_cls[reps], truth[reps]
    d = out["Suitability_Score"].to_numpy() - base_score[reps]
    haz = tr == "Hazardous"
    not_haz = tr != "Hazardous"
    return {"mean_delta_score": round(float(d.mean()), 4), "mean_abs_delta_score": round(float(np.abs(d).mean()), 4),
            "classification_stability_pct": round(float((cls_n == cls_b).mean() * 100), 3),
            "accuracy_vs_rule_truth_pct": round(float((cls_n == tr).mean() * 100), 3),
            "fatal_errors_hazardous_as_optimal": int((haz & (cls_n == "Optimal")).sum()),
            "hazardous_leaked_to_acceptable": int((haz & (cls_n == "Acceptable")).sum()),
            "hazardous_leakage_pct": round(float((haz & (cls_n != "Hazardous")).sum() / haz.sum() * 100), 3),
            "hazardous_leakage_to_acceptable_pct": round(float((haz & (cls_n == "Acceptable")).sum() / haz.sum() * 100), 3),
            "false_alarm_pct_safe_called_hazardous": round(float((not_haz & (cls_n == "Hazardous")).sum() / not_haz.sum() * 100), 3)}


def panel2() -> dict:
    rng = np.random.default_rng(SEED)
    base = pd.read_csv(ps.DATA_CSV)
    rough = pd.read_csv(OUTPUTS_DIR / "site_roughness.csv").set_index("Site_ID")["Roughness_m"]
    base_feat = base[FEATURES].reset_index(drop=True).copy()
    base_feat["Roughness_m"] = base["Site_ID"].map(rough).to_numpy()
    b_before, b_after = ps.predict_batch(base_feat, safety_factor=False), ps.predict_batch(base_feat, safety_factor=True)
    truth = truth_labels(base_feat[FEATURES]).to_numpy()
    n = len(base_feat)
    changed = np.flatnonzero(b_before["Safety_Class"].to_numpy() != b_after["Safety_Class"].to_numpy())
    noise_free = {"classes_before": b_before["Safety_Class"].value_counts().to_dict(),
                  "classes_after": b_after["Safety_Class"].value_counts().to_dict(),
                  "sites_reclassified": [{"site_id": base["Site_ID"].iloc[i], "slope_deg": float(base["Slope_deg"].iloc[i]),
                                          "from": b_before["Safety_Class"].iloc[i], "to": b_after["Safety_Class"].iloc[i]} for i in changed]}
    reps = np.tile(np.arange(n), N_RUNS)
    levels, total = [], 0
    for lv in NOISE_LEVELS:
        noisy = base_feat.iloc[reps].reset_index(drop=True).copy()
        m = len(noisy)
        noisy["Slope_deg"] = np.abs(noisy["Slope_deg"] + rng.normal(0, lv["slope_deg"], m))
        noisy["Elevation_m"] = noisy["Elevation_m"] + rng.normal(0, lv["elevation_m"], m)
        noisy["Sun_Visible_Pct"] = np.clip(noisy["Sun_Visible_Pct"] + rng.normal(0, lv["solar_pct"], m), 0, 100)
        t0 = time.perf_counter()
        o_before = ps.predict_batch(noisy, safety_factor=False)
        o_after = ps.predict_batch(noisy, safety_factor=True)
        dt = time.perf_counter() - t0
        total += m
        before = _mc_metrics(o_before, b_before["Safety_Class"].to_numpy(), b_before["Suitability_Score"].to_numpy(), truth, reps)
        after = _mc_metrics(o_after, b_after["Safety_Class"].to_numpy(), b_after["Suitability_Score"].to_numpy(), truth, reps)
        layer_rate = {k.replace("safety_", ""): round(float(o_after[k].mean() * 100), 3) for k in o_after.columns if k.startswith("safety_")}
        levels.append({**lv, "evaluations_per_pipeline": int(m), "seconds_both_pipelines": round(dt, 2), "before": before, "after": after,
                       "leakage_reduction_pct_points": round(before["hazardous_leakage_pct"] - after["hazardous_leakage_pct"], 3),
                       "leakage_reduction_relative_pct": round(100 * (1 - after["hazardous_leakage_pct"] / max(before["hazardous_leakage_pct"], 1e-9)), 1),
                       "safety_layer_trigger_rate_pct": layer_rate})
    return {"runs_per_site": N_RUNS, "sites": n, "total_evaluations": int(total), "noise_sigma_levels": NOISE_LEVELS,
            "noise_free_effect": noise_free, "levels": levels,
            "zero_fatal_errors": all(l[k]["fatal_errors_hazardous_as_optimal"] == 0 for l in levels for k in ("before", "after")),
            "leakage_reduced_at_every_level": all(l["leakage_reduction_pct_points"] > 0 for l in levels),
            "note": "Leakage = % of rule-based Hazardous samples classified Acceptable or Optimal under noise. Fatal error = "
                    "Hazardous predicted Optimal. Both pipelines see the same noisy samples; noise is 1-sigma Gaussian, slope noise "
                    "folded to stay >= 0, Sun visibility clipped to [0, 100]. False alarm = non-Hazardous site called Hazardous (the cost)."}


# ----------------------------------------------------------------------------
# Panel 3
# ----------------------------------------------------------------------------
def _monotone(y: np.ndarray, direction: str, tol: float) -> dict:
    d = np.diff(y)
    bad = d > tol if direction == "nonincreasing" else d < -tol
    worst = float(d.max() if direction == "nonincreasing" else -d.min())
    return {"direction": direction, "tolerance": tol, "violations": int(bad.sum()),
            "worst_reversal": round(max(worst, 0.0), 4), "pass": bool(not bad.any())}


def _unimodal(y: np.ndarray, x: np.ndarray, peak_range: tuple[float, float], tol: float = 1e-6) -> dict:
    """Rises (non-decreasing) to a single peak located in `peak_range`, then falls (non-increasing)."""
    k = int(np.argmax(y))
    up_bad = int((np.diff(y[: k + 1]) < -tol).sum())
    down_bad = int((np.diff(y[k:]) > tol).sum())
    ok_peak = peak_range[0] <= x[k] <= peak_range[1]
    return {"direction": "unimodal", "peak_at": float(x[k]), "expected_peak_range": list(peak_range),
            "violations": up_bad + down_bad, "pass": bool(up_bad == 0 and down_bad == 0 and ok_peak)}


def panel3() -> dict:
    slopes = np.arange(0.0, 25.01, 0.25)
    df = _frame([{"Slope_deg": s} for s in slopes])
    out = ps.predict_batch(df)
    final, raw = out["Suitability_Score"].to_numpy(), out["score_raw"].to_numpy()
    p3 = {"slope": {"slope_deg": slopes.tolist(), "score_final": np.round(final, 3).tolist(),
                    "score_ml_only": np.round(raw, 3).tolist(),
                    "monotone_final": _monotone(final, "nonincreasing", MONOTONE_TOL_PTS),
                    "monotone_ml_only": _monotone(raw, "nonincreasing", MONOTONE_TOL_PTS),
                    "cap_at_15deg_ok": bool(final[slopes > 15.0].max() <= 35.0)}}

    def avg_power(site, tilt, tower, area=10.0):
        e = ms.evaluate_scenario(ms.Scenario(site_id=site, tower_height_m=tower, panel_tilt_deg=tilt, panel_area_m2=area),
                                 include_timeline=False, include_windows=False, explain=False)
        return e["power_generation"]["average_power_watts"], e["power_generation"]["peak_power_watts"]

    pole, mid = "Auto_SP_065", "Auto_SP_099"  # -89.56 deg (100% lit) and -85.31 deg (intermittent)
    tilts = np.arange(0.0, 90.01, 2.5)
    tilt_avg = np.array([avg_power(pole, t, 5.0)[0] for t in tilts])
    tilt_avg_mid = np.array([avg_power(mid, t, 5.0)[0] for t in tilts])
    towers = np.arange(1.0, 20.01, 1.0)
    tw_pole = np.array([avg_power(pole, 88.0, h)[0] for h in towers])
    tw_mid = np.array([avg_power(mid, 88.0, h)[0] for h in towers])
    # physical expectation: panels should stand near vertical at the pole (Sun < ~6 deg above the horizon)
    p3["tilt"] = {"tilt_deg": tilts.tolist(), "avg_power_w_pole_site": np.round(tilt_avg, 2).tolist(),
                  "avg_power_w_mid_site": np.round(tilt_avg_mid, 2).tolist(), "pole_site": pole, "mid_site": mid,
                  "best_tilt_pole_deg": float(tilts[int(np.argmax(tilt_avg))]),
                  "best_tilt_mid_deg": float(tilts[int(np.argmax(tilt_avg_mid))]),
                  "unimodal_pole": _unimodal(tilt_avg, tilts, (80.0, 90.0)),
                  "unimodal_mid": _unimodal(tilt_avg_mid, tilts, (75.0, 90.0)),
                  "expectation": "optimum tilt ~ 90 deg minus the Sun elevation (<= ~6 deg at the pole), i.e. near-vertical",
                  "area_m2": 10.0, "tower_m": 5.0}
    p3["tower"] = {"tower_height_m": towers.tolist(), "avg_power_w_pole_site": np.round(tw_pole, 2).tolist(),
                   "avg_power_w_mid_site": np.round(tw_mid, 2).tolist(),
                   "horizon_boost_deg_at_1m": round(ms.tower_boost_deg(1.0), 5),
                   "horizon_boost_deg_at_20m": round(ms.tower_boost_deg(20.0), 5),
                   "gain_pct_1m_to_20m_pole": round(float((tw_pole[-1] / tw_pole[0] - 1) * 100), 3),
                   "gain_pct_1m_to_20m_mid": round(float((tw_mid[-1] / tw_mid[0] - 1) * 100), 3),
                   "monotone_pole": _monotone(tw_pole, "nondecreasing", 1e-6),
                   "monotone_mid": _monotone(tw_mid, "nondecreasing", 1e-6), "tilt_deg": 88.0, "area_m2": 10.0}
    p3["all_pass"] = bool(p3["slope"]["monotone_final"]["pass"] and p3["slope"]["cap_at_15deg_ok"]
                          and p3["tilt"]["unimodal_pole"]["pass"] and p3["tilt"]["unimodal_mid"]["pass"] and p3["tower"]["monotone_pole"]["pass"]
                          and p3["tower"]["monotone_mid"]["pass"])
    return p3


# ----------------------------------------------------------------------------
# Panel 4
# ----------------------------------------------------------------------------
def panel4() -> dict:
    rng = np.random.default_rng(SEED)
    base = pd.read_csv(ps.DATA_CSV)[FEATURES]
    pick = base.iloc[rng.integers(0, len(base), BENCH_SITES)].reset_index(drop=True)
    jitter = rng.normal(0, 0.05, pick.shape) * base.std().to_numpy()
    cand = (pick + jitter).clip(lower=base.min(), upper=base.max(), axis=1)
    cand["Slope_deg"] = cand["Slope_deg"].abs()
    ps.predict_batch(cand.iloc[:200])  # warm-up
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        out = ps.predict_batch(cand)
        times.append(time.perf_counter() - t0)
    best = min(times)
    s = ms.Scenario(site_id="Auto_SP_099")
    ms.evaluate_scenario(s)
    single = []
    for _ in range(20):
        t0 = time.perf_counter()
        ms.evaluate_scenario(s)
        single.append((time.perf_counter() - t0) * 1000)
    from ephemeris_series import calibrated_series
    d = pd.read_csv(ps.DATA_CSV).iloc[43]
    t0 = time.perf_counter()
    for _ in range(50):
        calibrated_series(float(d["Lat"]), float(d["Lon"]), d.to_dict())
    series_ms = (time.perf_counter() - t0) / 50 * 1000
    return {"n_sites": BENCH_SITES, "batch_ms_best": round(best * 1000, 1), "batch_ms_all_runs": [round(t * 1000, 1) for t in times],
            "sites_per_second": int(BENCH_SITES / best), "ms_per_1000_sites": round(best * 1000 / BENCH_SITES * 1000, 2),
            "class_mix": out["Safety_Class"].value_counts().to_dict(),
            "full_scenario_eval_ms_median": round(float(np.median(single)), 1),
            "full_scenario_eval_ms_p95": round(float(np.percentile(single, 95)), 1),
            "hourly_series_generation_ms": round(series_ms, 2),
            "scope": "batch = regressor + classifier + guardrails + OOD check; full scenario = 1441-h series, physics, "
                     "XAI, top-3 windows, timeline, ML + 300-tree uncertainty"}


# ----------------------------------------------------------------------------
# Figure
# ----------------------------------------------------------------------------
def make_figure(r1, r2, r3, r4, path: Path) -> dict:
    fig = plt.figure(figsize=(20, 14.5))
    gs = GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.18)

    # Panel 1: ML only vs guardrails + safety factor
    ax = fig.add_subplot(gs[0, 0])
    cases = r1["cases"]
    x = np.arange(len(cases))
    ax.bar(x - 0.2, [c["ml_only_score"] for c in cases], 0.38, color="#9aa5b1", label="ML only")
    ax.bar(x + 0.2, [c["guardrailed_score"] for c in cases], 0.38,
           color=[CLASS_COLORS[c["guardrailed_class"]] for c in cases], edgecolor="k", label="Guardrails + safety factor")
    for i, c in enumerate(cases):
        ax.text(i + 0.2, c["guardrailed_score"] + 1.5, c["guardrailed_class"][:4] + ("" if c["pass"] else " X"),
                ha="center", fontsize=8, fontweight="bold")
        ax.text(i - 0.2, c["ml_only_score"] + 1.5, c["ml_only_class"][:4], ha="center", fontsize=8, color="#444")
    ax.set_xticks(x)
    short = ["1\nIdeal", "2\nRim 24\u00b0\n100% Sun", "3\nPSR floor\n0% Sun", "4a\n4.8\u00b0", "4b\n5.3\u00b0", "5a\n14.5\u00b0", "5b\n15.6\u00b0"]
    ax.set_xticklabels(short, fontsize=9)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Suitability_Score")
    ax.set_title("Panel 1 - Adversarial & boundary trap matrix (7 cases)", fontweight="bold", fontsize=12)
    ax.axhline(35, color="#d62728", ls=":", lw=1)
    ax.legend(loc="upper right", fontsize=9, ncol=2)
    ax.grid(axis="y", alpha=0.3)

    # Panel 2: Monte Carlo leakage before vs after the 3-layer safety factor
    sub2 = gs[0, 1].subgridspec(1, 2, wspace=0.28)
    axl, axr = fig.add_subplot(sub2[0, 0]), fig.add_subplot(sub2[0, 1])
    lv = r2["levels"]
    xs = np.arange(len(lv))
    names = [f"\u00b1{l['slope_deg']}\u00b0" for l in lv]
    for ax_, key, ttl, ylab in ((axl, "hazardous_leakage_pct", "Hazardous leaked to Acceptable/Optimal", "% of Hazardous samples"),
                                (axr, "false_alarm_pct_safe_called_hazardous", "Cost: safe sites called Hazardous", "% of non-Hazardous samples")):
        b1 = ax_.bar(xs - 0.2, [l["before"][key] for l in lv], 0.38, color="#9aa5b1", label="Before")
        b2 = ax_.bar(xs + 0.2, [l["after"][key] for l in lv], 0.38, color="#2ca02c" if key.startswith("hazardous") else "#ff9f1c",
                     edgecolor="k", label="After safety factor")
        top = max(max(l["before"][key], l["after"][key]) for l in lv)
        for i, l in enumerate(lv):
            ax_.text(i - 0.2, l["before"][key] + top * 0.02, f"{l['before'][key]:.1f}", ha="center", fontsize=8)
            ax_.text(i + 0.2, l["after"][key] + top * 0.02, f"{l['after'][key]:.1f}", ha="center", fontsize=8, fontweight="bold")
        ax_.set_ylim(0, top * 1.22)
        ax_.set_xticks(xs)
        ax_.set_xticklabels(names, fontsize=9)
        ax_.set_xlabel("slope noise (1\u03c3)")
        ax_.set_ylabel(ylab, fontsize=9)
        ax_.set_title(ttl, fontsize=9.5, fontweight="bold")
        ax_.grid(axis="y", alpha=0.3)
    axl.legend(loc="upper left", fontsize=8)
    fat = sum(l[k]["fatal_errors_hazardous_as_optimal"] for l in lv for k in ("before", "after"))
    fig.text(0.515, 0.905, f"Panel 2 - Monte Carlo sensor noise ({r2['total_evaluations']:,} evaluations x 2 pipelines; fatal errors: {fat})",
             fontsize=12, fontweight="bold")

    # Panel 3: three sub-axes
    sub = gs[1, 0].subgridspec(1, 3, wspace=0.75)
    a1, a2, a3 = (fig.add_subplot(sub[0, i]) for i in range(3))
    s3 = r3["slope"]
    a1.plot(s3["slope_deg"], s3["score_ml_only"], color="#9aa5b1", label="ML only")
    a1.plot(s3["slope_deg"], s3["score_final"], color="#d62728", lw=2, label="Guardrails + SF")
    a1.axvline(15, color="k", ls=":", lw=1)
    a1.set_xlim(0, 25)
    a1.set_xlabel("Slope (deg)")
    a1.set_ylabel("Suitability_Score")
    a1.set_title("3a Score vs slope", fontsize=10, fontweight="bold")
    a1.legend(fontsize=7)
    a1.grid(alpha=0.3)
    t3 = r3["tilt"]
    a2.plot(t3["tilt_deg"], t3["avg_power_w_pole_site"], color="#1f77b4", lw=2, label=f"{t3['pole_site']} (-89.6°)")
    a2.plot(t3["tilt_deg"], t3["avg_power_w_mid_site"], color="#ff7f0e", lw=2, label=f"{t3['mid_site']} (-85.3°)")
    a2.set_xlim(0, 90)
    a2.set_xlabel("Panel tilt (deg)")
    a2.set_ylabel("Mean power (W), 10 m²")
    a2.set_title("3b Power vs tilt", fontsize=10, fontweight="bold")
    a2.legend(fontsize=7)
    a2.grid(alpha=0.3)
    w3 = r3["tower"]
    a3.plot(w3["tower_height_m"], w3["avg_power_w_pole_site"], color="#1f77b4", lw=2, label="pole site")
    a3.plot(w3["tower_height_m"], w3["avg_power_w_mid_site"], color="#ff7f0e", lw=2, label="mid site")
    a3.set_xlim(1, 20)
    a3.set_xlabel("Tower height (m)")
    a3.set_ylabel("Mean power (W), tilt 88°")
    a3.set_title("3c Power vs tower", fontsize=10, fontweight="bold")
    a3.legend(fontsize=7)
    a3.grid(alpha=0.3)
    fig.text(0.125, 0.487, "Panel 3 - Physical monotonicity & solar-hardware sensitivity", fontsize=12, fontweight="bold")

    # Panel 4: throughput
    ax = fig.add_subplot(gs[1, 1])
    labels = [f"Batch inference\n({r4['n_sites']:,} sites)", "Full scenario\n(median)", "Hourly series\ngeneration"]
    vals = [r4["batch_ms_best"], r4["full_scenario_eval_ms_median"], r4["hourly_series_generation_ms"]]
    ax.barh(labels, vals, color=["#1f77b4", "#2ca02c", "#9467bd"])
    ax.set_xscale("log")
    ax.set_xlabel("Latency (ms, log scale)")
    for i, v in enumerate(vals):
        ax.text(v * 1.15, i, f"{v:,.1f} ms", va="center", fontsize=10, fontweight="bold")
    ax.set_xlim(0.5, max(vals) * 12)
    ax.set_title(f"Panel 4 - Surrogate throughput: {r4['sites_per_second']:,} sites/s", fontweight="bold", fontsize=12)
    ax.grid(axis="x", alpha=0.3)
    fig.suptitle("Lunar Landing Site Navigator - engineering stress test", fontsize=16, fontweight="bold", y=0.96)
    overlaps = find_text_overlaps(fig)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"overlaps": overlaps}


def main() -> None:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    print("Panel 1: adversarial & boundary matrix ...", flush=True)
    r1 = panel1()
    print("Panel 2: Monte Carlo (300,000 evaluations) ...", flush=True)
    r2 = panel2()
    print("Panel 3: monotonicity & hardware sensitivity ...", flush=True)
    r3 = panel3()
    print("Panel 4: throughput ...", flush=True)
    r4 = panel4()
    fig_path = OUTPUTS_DIR / "stress_test_dashboard.png"
    layout = make_figure(r1, r2, r3, r4, fig_path)
    try:
        eval_layout = json.loads((OUTPUTS_DIR / "figure_layout_report.json").read_text())
    except Exception:
        eval_layout = {"error": "run train_and_evaluate.py first"}
    results = {"generated_utc": datetime.now(timezone.utc).isoformat(), "seed": SEED,
               "panel1_adversarial_boundary": r1, "panel2_monte_carlo": r2, "panel3_monotonicity_hardware": r3,
               "panel4_throughput": r4, "figure_layout": {"stress_test_dashboard.png": layout["overlaps"]},
               "model_evaluation_png_layout": eval_layout,
               "summary": {"panel1_all_pass": r1["all_pass"], "panel2_zero_fatal_errors": r2["zero_fatal_errors"],
                           "panel2_leakage_before_after_pct": {l["name"]: [l["before"]["hazardous_leakage_pct"], l["after"]["hazardous_leakage_pct"]] for l in r2["levels"]},
                           "panel2_leakage_reduced_at_every_level": r2["leakage_reduced_at_every_level"],
                           "panel3_all_pass": r3["all_pass"], "panel4_sites_per_second": r4["sites_per_second"],
                           "stress_figure_text_overlaps": len(layout["overlaps"]),
                           "model_evaluation_text_overlaps": (eval_layout.get("text_overlaps", {}) or {}).get("model_evaluation.png")}}
    (OUTPUTS_DIR / "stress_test_results.json").write_text(json.dumps(ms.to_jsonable(results), indent=2))
    print(json.dumps(results["summary"], indent=2))
    print("saved:", OUTPUTS_DIR / "stress_test_results.json", "and", fig_path)


if __name__ == "__main__":
    main()
