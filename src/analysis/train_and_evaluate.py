"""Train, cross-validate and explain landing-site suitability models.

Run from the repo root:  python src/analysis/train_and_evaluate.py

Outputs
  models/best_regressor.joblib, models/best_classifier.joblib
  outputs/ranked_lunar_sites.csv
  outputs/feature_importance.png, polar_suitability_map.png, model_evaluation.png (300 DPI)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, confusion_matrix, f1_score,
                             mean_absolute_error, mean_squared_error, r2_score)
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

sys.path.insert(0, str(Path(__file__).resolve().parent))
from suitability import CLASSES, DATA_CSV, FEATURES, MODELS_DIR, OUTPUTS_DIR, add_labels  # noqa: E402

SEED = 42
N_SPLITS = 5
DPI = 300
CLASS_COLORS = {"Optimal": "#2ca02c", "Acceptable": "#ff9f1c", "Hazardous": "#d62728"}


LAYOUT_REPORT: dict[str, list[str]] = {}


def find_text_overlaps(fig, tol_px: float = 1.0) -> list[str]:
    """Descriptions of visible text artists (titles, labels, ticks, annotations, legend) whose boxes intersect."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    items = []
    for ax in fig.axes:
        xl, yl = sorted(ax.get_xlim()), sorted(ax.get_ylim())
        eps_x, eps_y = 1e-9 + 1e-6 * (xl[1] - xl[0]), 1e-9 + 1e-6 * (yl[1] - yl[0])
        xt = [lab for lab in ax.get_xticklabels() if xl[0] - eps_x <= lab.get_position()[0] <= xl[1] + eps_x]
        yt = [lab for lab in ax.get_yticklabels() if yl[0] - eps_y <= lab.get_position()[1] <= yl[1] + eps_y]
        arts = [ax.title, ax.xaxis.label, ax.yaxis.label, *xt, *yt, *ax.texts]
        leg = ax.get_legend()
        if leg is not None:
            arts += list(leg.get_texts())
        items += [a for a in arts if a.get_visible() and a.get_text().strip()]
    if fig._suptitle is not None:
        items.append(fig._suptitle)
    boxes = [(a.get_text().replace("\n", " ")[:30], a.get_window_extent(renderer)) for a in items]
    out = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (na, a), (nb, b) = boxes[i], boxes[j]
            if a.x0 < b.x1 - tol_px and b.x0 < a.x1 - tol_px and a.y0 < b.y1 - tol_px and b.y0 < a.y1 - tol_px:
                out.append(f"'{na}' overlaps '{nb}'")
    return out


def _save(fig, path: Path) -> None:
    """Record text-overlap findings for the figure, then save it at 300 DPI."""
    LAYOUT_REPORT[Path(path).name] = find_text_overlaps(fig)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")


def regressors() -> dict:
    """Candidate regressors (scaling inside pipelines so CV has no leakage)."""
    models = {
        "RandomForest": RandomForestRegressor(n_estimators=300, random_state=SEED),
        "GradientBoosting": GradientBoostingRegressor(random_state=SEED),
        "Ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "SVR": make_pipeline(StandardScaler(), SVR(C=50.0, epsilon=0.5)),
    }
    try:  # optional
        from xgboost import XGBRegressor
        models["XGBoost"] = XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, random_state=SEED)
    except ImportError:
        pass
    return models


def cv_regression(model, X, y, kf):
    """5-fold CV; returns per-fold metric arrays and out-of-fold predictions."""
    oof = np.zeros(len(y))
    r2, rmse, mae = [], [], []
    for tr, te in kf.split(X):
        m = _clone(model).fit(X.iloc[tr], y[tr])
        p = m.predict(X.iloc[te])
        oof[te] = p
        r2.append(r2_score(y[te], p))
        rmse.append(np.sqrt(mean_squared_error(y[te], p)))
        mae.append(mean_absolute_error(y[te], p))
    return {"R2": np.array(r2), "RMSE": np.array(rmse), "MAE": np.array(mae)}, oof


def _clone(model):
    from sklearn.base import clone
    return clone(model)


def plot_feature_importance(reg, clf, X, y, labels, path):
    """Permutation importance (regressor, classifier) - model-agnostic XAI."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, model, target, title, scoring in [
        (axes[0], reg, y, "Suitability_Score regressor\n(drop in R²)", "r2"),
        (axes[1], clf, labels, "Safety_Class classifier\n(drop in accuracy)", "accuracy"),
    ]:
        res = permutation_importance(model, X, target, n_repeats=30, random_state=SEED, scoring=scoring)
        order = np.argsort(res.importances_mean)
        ax.barh(np.array(FEATURES)[order], res.importances_mean[order], xerr=res.importances_std[order],
                color="#1f77b4", ecolor="#444", capsize=3)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_xlabel("Permutation importance")
        ax.grid(axis="x", alpha=0.3)
    fig.suptitle("Which physical parameters drive lunar landing suitability?", fontsize=14, fontweight="bold")
    fig.tight_layout()
    _save(fig, path)
    plt.close(fig)


def plot_polar_map(df, path):
    """South-pole polar projection: radius = degrees from pole, angle = east longitude."""
    fig = plt.figure(figsize=(9, 9))
    ax = fig.add_subplot(111, projection="polar")
    theta = np.deg2rad(df["Lon"].to_numpy())
    r = 90.0 + df["Lat"].to_numpy()  # 0 at pole, 5 at -85
    for cls in CLASSES:
        m = (df["Safety_Class"] == cls).to_numpy()
        ax.scatter(theta[m], r[m], s=45, c=CLASS_COLORS[cls], edgecolor="k", linewidth=0.4,
                   label=f"{cls} ({m.sum()})", zorder=3)
    top = df.nsmallest(5, "Rank")
    ax.scatter(np.deg2rad(top["Lon"]), 90.0 + top["Lat"], s=420, marker="*", c="gold",
               edgecolor="black", linewidth=1.2, label="Top 5 recommended", zorder=5)
    for _, row in top.iterrows():
        ax.annotate(f"#{int(row['Rank'])}", (np.deg2rad(row["Lon"]), 90.0 + row["Lat"]),
                    xytext=(8, 8), textcoords="offset points", fontsize=10, fontweight="bold", zorder=6)
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["-89°", "-88°", "-87°", "-86°", "-85°"])
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_title("Lunar South Pole landing-site suitability (-85° to -90°)\nangle = east longitude",
                 fontsize=13, fontweight="bold", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1))
    _save(fig, path)
    plt.close(fig)


def plot_evaluation(y, oof, labels, oof_cls, path):
    """Predicted-vs-actual scatter (out-of-fold) + confusion matrix."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8))
    ax = axes[0]
    ax.scatter(y, oof, c="#1f77b4", edgecolor="k", linewidth=0.3, alpha=0.8)
    lo, hi = min(y.min(), oof.min()) - 2, max(y.max(), oof.max()) + 2
    ax.plot([lo, hi], [lo, hi], "r--", label="Ideal")
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("Actual Suitability_Score"); ax.set_ylabel("Predicted (5-fold out-of-fold)")
    ax.set_title(f"Regression: R² = {r2_score(y, oof):.3f}, RMSE = {np.sqrt(mean_squared_error(y, oof)):.2f}",
                 fontweight="bold")
    ax.legend(); ax.grid(alpha=0.3)
    cm = confusion_matrix(labels, oof_cls, labels=CLASSES)
    ConfusionMatrixDisplay(cm, display_labels=CLASSES).plot(ax=axes[1], cmap="Blues", colorbar=False)
    axes[1].set_title(f"Safety_Class (out-of-fold), acc = {accuracy_score(labels, oof_cls):.3f}", fontweight="bold")
    fig.tight_layout()
    _save(fig, path)
    plt.close(fig)


def main() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    OUTPUTS_DIR.mkdir(exist_ok=True)
    df = add_labels(pd.read_csv(DATA_CSV))
    X, y, labels = df[FEATURES], df["Suitability_Score"].to_numpy(), df["Safety_Class"].to_numpy()
    print("Class counts:", df["Safety_Class"].value_counts().to_dict())

    # ---- Regression model comparison ----
    kf = KFold(N_SPLITS, shuffle=True, random_state=SEED)
    results, oofs = {}, {}
    for name, model in regressors().items():
        results[name], oofs[name] = cv_regression(model, X, y, kf)
    summary = pd.DataFrame({n: {f"{k}_mean": v.mean() for k, v in r.items()} | {f"{k}_std": v.std() for k, v in r.items()}
                            for n, r in results.items()}).T[
        ["R2_mean", "R2_std", "RMSE_mean", "RMSE_std", "MAE_mean", "MAE_std"]]
    summary = summary.sort_values("RMSE_mean")
    best_name = summary.index[0]
    print(f"\n=== {N_SPLITS}-fold CV: regressors (ranked by RMSE) ===\n{summary.round(4).to_string()}")
    best_reg = _clone(regressors()[best_name]).fit(X, y)

    # ---- Classifier (stratified if every class has >= N_SPLITS members) ----
    min_count = pd.Series(labels).value_counts().min()
    cv_cls = (StratifiedKFold(N_SPLITS, shuffle=True, random_state=SEED) if min_count >= N_SPLITS
              else KFold(N_SPLITS, shuffle=True, random_state=SEED))
    if min_count < N_SPLITS:
        print(f"WARNING: smallest class has {min_count} samples; using plain KFold.")
    clf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=SEED)
    oof_cls = cross_val_predict(clf, X, labels, cv=cv_cls)
    accs, f1s = [], []
    for tr, te in cv_cls.split(X, labels):
        p = _clone(clf).fit(X.iloc[tr], labels[tr]).predict(X.iloc[te])
        accs.append(accuracy_score(labels[te], p))
        f1s.append(f1_score(labels[te], p, average="macro"))
    print(f"\n=== {N_SPLITS}-fold CV: RandomForestClassifier ===\n"
          f"Accuracy = {np.mean(accs):.4f} +/- {np.std(accs):.4f}\n"
          f"Macro F1 = {np.mean(f1s):.4f} +/- {np.std(f1s):.4f}")
    best_clf = _clone(clf).fit(X, labels)

    # ---- Export ----
    joblib.dump({"model": best_reg, "name": best_name, "features": FEATURES}, MODELS_DIR / "best_regressor.joblib")
    joblib.dump({"model": best_clf, "name": "RandomForestClassifier", "features": FEATURES, "classes": list(best_clf.classes_)},
                MODELS_DIR / "best_classifier.joblib")
    rf_unc = RandomForestRegressor(n_estimators=300, random_state=SEED).fit(X, y)
    joblib.dump({"model": rf_unc, "features": FEATURES}, MODELS_DIR / "uncertainty_ensemble.joblib")
    (OUTPUTS_DIR / "cv_metrics.json").write_text(json.dumps({
        "regressors": summary.round(5).to_dict("index"),
        "classifier": {"accuracy_mean": float(np.mean(accs)), "accuracy_std": float(np.std(accs)),
                       "macro_f1_mean": float(np.mean(f1s)), "macro_f1_std": float(np.std(f1s))}}, indent=2))

    ranked = df.assign(Predicted_Score=oofs[best_name], Predicted_Class=oof_cls)
    ranked = ranked.sort_values(["Suitability_Score", "Slope_deg"], ascending=[False, True]).reset_index(drop=True)
    ranked.insert(0, "Rank", np.arange(1, len(ranked) + 1))
    ranked.to_csv(OUTPUTS_DIR / "ranked_lunar_sites.csv", index=False)

    # ---- Plots ----
    plot_feature_importance(best_reg, best_clf, X, y, labels, OUTPUTS_DIR / "feature_importance.png")
    plot_polar_map(ranked, OUTPUTS_DIR / "polar_suitability_map.png")
    plot_evaluation(y, oofs[best_name], labels, oof_cls, OUTPUTS_DIR / "model_evaluation.png")

    (OUTPUTS_DIR / "figure_layout_report.json").write_text(json.dumps(
        {"dpi": DPI, "text_overlaps": LAYOUT_REPORT, "total_overlaps": sum(len(v) for v in LAYOUT_REPORT.values())}, indent=2))
    print("Figure text-overlap check:", {k: len(v) for k, v in LAYOUT_REPORT.items()})

    cols = ["Rank", "Site_ID", "Lat", "Lon", "Slope_deg", "Sun_Visible_Pct", "Earth_Visible_Pct",
            "Suitability_Score", "Safety_Class"]
    print(f"\n=== Top 5 landing sites ===\n{ranked[cols].head(5).round(2).to_string(index=False)}")
    print(f"\nBest regressor: {best_name}. Artifacts in {MODELS_DIR} and {OUTPUTS_DIR}")


if __name__ == "__main__":
    main()
