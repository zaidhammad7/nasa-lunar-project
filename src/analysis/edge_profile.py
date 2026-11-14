"""Edge-AI profile of the landing-site models: accuracy, footprint, worst-case compute, quantization and offline data.

    python src/analysis/edge_profile.py

Writes
  outputs/edge_profile.json            every number below
  outputs/edge/lunar_models.h          the three tree ensembles exported as plain C arrays + a C predict function
                                       (no Python, no heap; model in flash/ROM as const data)

What is measured here (exact) and what is estimated (marked "estimate"):
  exact     train / test accuracy, tree counts, nodes, depths, exported C array sizes, comparisons per inference (worst and
            average), working RAM of the C predictor, quantization error (float32 / float16 / int16 / int8), offline data sizes
  measured  single-sample latency on THIS laptop (Python / scikit-learn and NumPy tree walk)
  estimate  latency and energy on a target flight processor: cycles-per-node x node visits / clock, energy = power x time.
            The real figure needs the C header compiled and timed on the target chip.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import accuracy_score, mean_squared_error, r2_score
from sklearn.model_selection import KFold, train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ephemeris_series as es  # noqa: E402
import horizon as hz  # noqa: E402
from suitability import DATA_CSV, FEATURES, MODELS_DIR, OUTPUTS_DIR, TRAINING_CSV, add_labels  # noqa: E402

SEED, N_SPLITS = 42, 5
EDGE_DIR = OUTPUTS_DIR / "edge"
CYCLES_PER_NODE = (6, 12)  # estimate: load feature index + threshold, compare, branch, load child on an in-order core
TARGET_CLOCKS_MHZ = (50, 100, 200)
ASSUMED_POWER_W = (0.1, 1.0)  # placeholders for energy = P x t; replace with the target board's measured power


# ----------------------------------------------------------------------------------------------------------- data & models
def load():
    df = add_labels(pd.read_csv(TRAINING_CSV if TRAINING_CSV.exists() else DATA_CSV))
    X, y, labels = df[FEATURES], df["Suitability_Score"].to_numpy(), df["Safety_Class"].to_numpy()
    reg = joblib.load(MODELS_DIR / "best_regressor.joblib")["model"]
    clf = joblib.load(MODELS_DIR / "best_classifier.joblib")["model"]
    unc = joblib.load(MODELS_DIR / "uncertainty_ensemble.joblib")["model"]
    return df, X, y, labels, reg, clf, unc


def trees_of(model) -> list:
    return [e.tree_ for e in np.ravel(model.estimators_)]


# ----------------------------------------------------------------------------------------------------------- 0. accuracy
def accuracy(X, y, labels, reg, clf, unc) -> dict:
    kf = KFold(N_SPLITS, shuffle=True, random_state=SEED)
    oof_reg, oof_unc, oof_cls = np.zeros(len(y)), np.zeros(len(y)), np.empty(len(y), dtype=object)
    for tr, te in kf.split(X):
        oof_reg[te] = clone(reg).fit(X.iloc[tr], y[tr]).predict(X.iloc[te])
        oof_unc[te] = clone(unc).fit(X.iloc[tr], y[tr]).predict(X.iloc[te])
        oof_cls[te] = clone(clf).fit(X.iloc[tr], labels[tr]).predict(X.iloc[te])
    Xtr, Xte, ytr, yte, ltr, lte = train_test_split(X, y, labels, test_size=0.2, random_state=SEED)
    h_reg = clone(reg).fit(Xtr, ytr)
    h_clf = clone(clf).fit(Xtr, ltr)

    def reg_metrics(yt, p):
        return {"R2": round(float(r2_score(yt, p)), 4), "RMSE_pts": round(float(np.sqrt(mean_squared_error(yt, p))), 3)}
    return {
        "dataset": {"sites": int(len(y)), "features": FEATURES, "n_features": len(FEATURES),
                    "classes": pd.Series(labels).value_counts().to_dict()},
        "regressor_GradientBoosting": {
            "train_in_sample": reg_metrics(y, reg.predict(X)),
            "test_5fold_cv": reg_metrics(y, oof_reg),
            "test_holdout_20pct": reg_metrics(yte, h_reg.predict(Xte)) | {"train_R2_80pct": round(float(r2_score(ytr, h_reg.predict(Xtr))), 4)}},
        "classifier_RandomForest": {
            "train_in_sample_accuracy": round(float(accuracy_score(labels, clf.predict(X))), 4),
            "test_5fold_cv_accuracy": round(float(accuracy_score(labels, oof_cls)), 4),
            "test_holdout_20pct_accuracy": round(float(accuracy_score(lte, h_clf.predict(Xte))), 4),
            "train_80pct_accuracy": round(float(accuracy_score(ltr, h_clf.predict(Xtr))), 4)},
        "uncertainty_RandomForest": {"train_in_sample": reg_metrics(y, unc.predict(X)), "test_5fold_cv": reg_metrics(y, oof_unc)},
        "note": "100 sites in total, so test sets are small (20 sites per fold / hold-out): treat test figures as +/- a few points.",
    }


# ----------------------------------------------------------------------------------------------------------- 1. footprint
# Flat C layout per ensemble (all trees concatenated, child indices relative to the ensemble):
#   uint8  feat[node]   feature index, 0xFF = leaf
#   float  thr[node]    split threshold (internal nodes) - float32 or float64
#   uint16 left[node], right[node]   child node indices (uint32 if an ensemble has >= 65535 nodes)
#   leaf payload: GB regressor 1 float (learning-rate-scaled), RF classifier 3 x float (class probabilities), RF regressor 1 float
#   uint32 root[tree]
def flatten(model, kind: str) -> dict:
    feat, thr, left, right, leaf, roots = [], [], [], [], [], []
    base = 0
    lr = getattr(model, "learning_rate", 1.0)
    for t in trees_of(model):
        roots.append(base)
        for i in range(t.node_count):
            is_leaf = t.children_left[i] == -1
            feat.append(255 if is_leaf else int(t.feature[i]))
            thr.append(0.0 if is_leaf else float(t.threshold[i]))
            left.append(base + int(t.children_left[i]) if not is_leaf else 0)
            right.append(base + int(t.children_right[i]) if not is_leaf else 0)
            v = t.value[i]
            if kind == "classifier":
                leaf.append((v[0] / v[0].sum()).tolist())
            elif kind == "gbr":
                leaf.append([float(v[0][0]) * lr])
            else:
                leaf.append([float(v[0][0])])
        base += t.node_count
    out = {k: np.array(v) for k, v in dict(feat=feat, thr=thr, left=left, right=right, leaf=leaf, roots=roots).items()}
    out["n_nodes"], out["n_trees"], out["kind"] = base, len(roots), kind
    if kind == "gbr":
        out["init"] = float(np.ravel(model.init_.constant_)[0]) if hasattr(model.init_, "constant_") else float(model._raw_predict_init(np.zeros((1, len(FEATURES))))[0][0])
    return out


def flash_bytes(f: dict, thr_bytes: int, leaf_bytes: int) -> dict:
    n, idx = f["n_nodes"], (2 if f["n_nodes"] < 65535 else 4)
    leaves_per_node = f["leaf"].shape[1]
    parts = {"feature_index_u8": n, "threshold": n * thr_bytes, "children": 2 * n * idx,
             "leaf_values": n * leaves_per_node * leaf_bytes, "tree_roots_u32": f["n_trees"] * 4}
    return parts | {"total_bytes": sum(parts.values())}


def footprint(models: dict) -> dict:
    out = {}
    for name, (m, kind) in models.items():
        f = flatten(m, kind)
        tr = trees_of(m)
        out[name] = {
            "trees": f["n_trees"], "total_nodes": f["n_nodes"], "split_nodes": int(sum(t.node_count - t.n_leaves for t in tr)),
            "leaves": int(sum(t.n_leaves for t in tr)), "max_depth": int(max(t.max_depth for t in tr)),
            "flash_float64": flash_bytes(f, 8, 8), "flash_float32": flash_bytes(f, 4, 4),
            "flash_int16_fixed_point": flash_bytes(f, 2, 2), "flash_int8_thresholds_int16_leaves": flash_bytes(f, 1, 2),
            "joblib_file_bytes": int((MODELS_DIR / {"regressor_GradientBoosting": "best_regressor.joblib",
                                                     "classifier_RandomForest": "best_classifier.joblib",
                                                     "uncertainty_RandomForest": "uncertainty_ensemble.joblib"}[name]).stat().st_size),
        }
    return out


# ----------------------------------------------------------------------------------------------------------- C export
def write_c_header(models: dict, path: Path) -> int:
    """Emit const float32 arrays (+ predict functions). Returns the header's size on disk (text; flash use is the array bytes)."""
    lines = ["/* Lunar landing-site models exported from scikit-learn by src/analysis/edge_profile.py.",
             f" * Inputs (float, this order): {', '.join(FEATURES)}.",
             " * All model data is const (flash / ROM). Prediction uses no heap; working RAM is a few dozen bytes on the stack.",
             " * Tree walk: if (x[feat] <= thr) go left else right, until feat == 0xFF (leaf). */",
             "#ifndef LUNAR_MODELS_H", "#define LUNAR_MODELS_H", "#include <stdint.h>", f"#define LUNAR_N_FEATURES {len(FEATURES)}", ""]
    for name, (m, kind) in models.items():
        f = flatten(m, kind)
        p = name.split("_")[0].upper()[:3] + "_" + kind.upper()[:3]
        it = "uint16_t" if f["n_nodes"] < 65535 else "uint32_t"
        fl = lambda a: ", ".join(f"{float(v):.9g}f" for v in a)  # noqa: E731
        lines += [f"/* {name}: {f['n_trees']} trees, {f['n_nodes']} nodes */",
                  f"#define {p}_N_TREES {f['n_trees']}",
                  f"static const uint32_t {p}_ROOT[{f['n_trees']}] = {{{', '.join(map(str, f['roots']))}}};",
                  f"static const uint8_t {p}_FEAT[{f['n_nodes']}] = {{{', '.join(map(str, f['feat']))}}};",
                  f"static const float {p}_THR[{f['n_nodes']}] = {{{fl(f['thr'])}}};",
                  f"static const {it} {p}_LEFT[{f['n_nodes']}] = {{{', '.join(map(str, f['left']))}}};",
                  f"static const {it} {p}_RIGHT[{f['n_nodes']}] = {{{', '.join(map(str, f['right']))}}};",
                  f"static const float {p}_LEAF[{f['n_nodes'] * f['leaf'].shape[1]}] = {{{fl(f['leaf'].ravel())}}};", ""]
        walk = (f"  uint32_t n = {p}_ROOT[t];\n  while ({p}_FEAT[n] != 0xFFu) n = (x[{p}_FEAT[n]] <= {p}_THR[n]) ? {p}_LEFT[n] : {p}_RIGHT[n];\n")
        if kind == "gbr":
            lines += [f"/* Suitability score (0-100 scale, before guardrails). */",
                      f"static inline float lunar_score(const float x[LUNAR_N_FEATURES]) {{",
                      f"  float s = {f['init']:.9g}f;",
                      f"  for (uint32_t t = 0; t < {p}_N_TREES; ++t) {{\n  {walk}    s += {p}_LEAF[n];\n  }}", "  return s;", "}", ""]
        elif kind == "classifier":
            lines += [f"/* Class probabilities out[3] in order {list(m.classes_)}. */",
                      f"static inline void lunar_class_proba(const float x[LUNAR_N_FEATURES], float out[3]) {{",
                      "  out[0] = out[1] = out[2] = 0.0f;",
                      f"  for (uint32_t t = 0; t < {p}_N_TREES; ++t) {{\n  {walk}    out[0] += {p}_LEAF[3u*n]; out[1] += {p}_LEAF[3u*n+1u]; out[2] += {p}_LEAF[3u*n+2u];\n  }}",
                      f"  out[0] /= {p}_N_TREES; out[1] /= {p}_N_TREES; out[2] /= {p}_N_TREES;", "}", ""]
        else:
            lines += ["/* Ensemble mean and standard deviation (score uncertainty). */",
                      f"static inline void lunar_uncertainty(const float x[LUNAR_N_FEATURES], float *mean, float *sd) {{",
                      "  float s = 0.0f, s2 = 0.0f;",
                      f"  for (uint32_t t = 0; t < {p}_N_TREES; ++t) {{\n  {walk}    float v = {p}_LEAF[n]; s += v; s2 += v * v;\n  }}",
                      f"  *mean = s / {p}_N_TREES; *sd = sqrtf(s2 / {p}_N_TREES - (*mean) * (*mean));", "}", ""]
    lines += ["#endif /* LUNAR_MODELS_H */", ""]
    lines.insert(lines.index("#include <stdint.h>") + 1, "#include <math.h>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path.stat().st_size


# ----------------------------------------------------------------------------------------------------------- 2. compute
def walk(f: dict, X: np.ndarray, thr=None, xq=None) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised walk of every tree for every row: returns (leaf index per tree x row, node visits per row)."""
    thr = f["thr"] if thr is None else thr
    x = X if xq is None else xq
    leaves = np.zeros((f["n_trees"], len(x)), dtype=np.int64)
    visits = np.zeros(len(x), dtype=np.int64)
    for k, r in enumerate(f["roots"]):
        node = np.full(len(x), r)
        while True:
            internal = f["feat"][node] != 255
            if not internal.any():
                break
            visits += internal
            fi = np.where(internal, f["feat"][node], 0)
            go_left = x[np.arange(len(x)), fi] <= thr[node]
            node = np.where(internal, np.where(go_left, f["left"][node], f["right"][node]), node)
        leaves[k] = node
    return leaves, visits


def compute(models: dict, X: pd.DataFrame) -> dict:
    out = {}
    Xn = X.to_numpy(np.float64)
    for name, (m, kind) in models.items():
        f = flatten(m, kind)
        tr = trees_of(m)
        _, visits = walk(f, Xn)
        x1 = X.iloc[[0]]
        t_skl = []
        for _ in range(300):
            t0 = time.perf_counter(); (m.predict_proba(x1) if kind == "classifier" else m.predict(x1)); t_skl.append(time.perf_counter() - t0)
        worst = int(sum(t.max_depth for t in tr))
        est = {f"{mhz}MHz": [round(worst * c / mhz, 1) for c in CYCLES_PER_NODE] for mhz in TARGET_CLOCKS_MHZ}
        out[name] = {
            "comparisons_worst_case_sum_of_tree_depths": worst,
            "comparisons_bound_max_depth_x_trees": int(max(t.max_depth for t in tr) * len(tr)),
            "comparisons_average_on_100_sites": round(float(visits.mean()), 1),
            "float_additions": len(tr) * (3 if kind == "classifier" else 1),
            "latency_this_laptop_sklearn_batch1_us_median": round(float(np.median(t_skl)) * 1e6, 1),
            "latency_target_estimate_us_worst_case": est | {"assumption": f"{CYCLES_PER_NODE[0]}-{CYCLES_PER_NODE[1]} cycles per tree node, no cache misses"},
            "energy_estimate_uJ_per_inference_at_100MHz": {f"{p}W": [round(worst * c / 100 * p, 2) for c in CYCLES_PER_NODE] for p in ASSUMED_POWER_W},
        }
    return out


def working_ram() -> dict:
    """Stack / RAM of the exported C predictor for one sample (model arrays live in flash)."""
    inputs = len(FEATURES) * 4
    return {"inputs_float32_bytes": inputs,
            "lunar_score": {"accumulator": 4, "tree_and_node_index": 8, "total_bytes": inputs + 12},
            "lunar_class_proba": {"accumulators": 12, "tree_and_node_index": 8, "total_bytes": inputs + 20},
            "lunar_uncertainty": {"accumulators": 12, "tree_and_node_index": 8, "total_bytes": inputs + 20},
            "all_three_sequentially_peak_bytes": inputs + 20 + 16,
            "note": "excludes the call-frame overhead of the compiler / ABI (typically 16-64 bytes). Feature extraction can stream "
                    "the hourly Sun / Earth elevations with running sums, so it also needs O(1) RAM (~64 bytes)."}


# ----------------------------------------------------------------------------------------------------------- 3. quantization
def quantize_affine(v: np.ndarray, lo: float, hi: float, bits: int, ceil: bool = False) -> np.ndarray:
    levels = 2 ** bits - 1
    s = (np.clip(v, lo, hi) - lo) / np.maximum(hi - lo, 1e-12) * levels  # per-feature ranges are arrays
    return np.ceil(s - 1e-9) if ceil else np.round(s)


def predict_q(f: dict, X: np.ndarray, scheme: str, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Ensemble output with thresholds / inputs / leaves stored in a reduced format."""
    if scheme in ("float32", "float16"):
        dt = np.float32 if scheme == "float32" else np.float16
        thr, xq = f["thr"].astype(dt).astype(np.float64), X.astype(dt).astype(np.float64)
        leaf = f["leaf"].astype(dt).astype(np.float64)
    else:
        bits = 16 if scheme == "int16" else 8
        fi = np.clip(f["feat"], 0, len(FEATURES) - 1)
        # per-feature affine fixed point; a threshold t becomes ceil(q(t)) so that x <= t  <=>  q(x) <= ceil(q(t)) (up to rounding)
        thr = np.where(f["feat"] == 255, 0, quantize_affine(f["thr"], lo[fi], hi[fi], bits, ceil=True))
        xq = np.column_stack([quantize_affine(X[:, j], lo[j], hi[j], bits) for j in range(X.shape[1])])
        lmin, lmax = f["leaf"].min(), f["leaf"].max()
        lq = quantize_affine(f["leaf"], lmin, lmax, 16)
        leaf = lmin + lq / (2 ** 16 - 1) * (lmax - lmin)
    leaves, _ = walk(f, X, thr=thr, xq=xq)
    vals = leaf[leaves]  # trees x rows x outputs
    if f["kind"] == "gbr":
        return f["init"] + vals[..., 0].sum(axis=0)
    if f["kind"] == "classifier":
        return vals.mean(axis=0)
    return vals[..., 0].mean(axis=0)


def quantization(models: dict, X: pd.DataFrame, y: np.ndarray, labels: np.ndarray, clf_classes) -> dict:
    Xn = X.to_numpy(np.float64)
    lo, hi = Xn.min(axis=0), Xn.max(axis=0)
    rng = np.random.default_rng(SEED)
    stress = lo + rng.random((10_000, Xn.shape[1])) * (hi - lo)  # 10,000 synthetic sites spanning the training ranges
    out = {}
    for name, (m, kind) in models.items():
        f = flatten(m, kind)
        res = {}
        for scheme in ("float64", "float32", "float16", "int16", "int8"):
            if scheme == "float64":
                p_real = (m.predict_proba(X) if kind == "classifier" else m.predict(X))
                p_str = (m.predict_proba(pd.DataFrame(stress, columns=FEATURES)) if kind == "classifier" else m.predict(pd.DataFrame(stress, columns=FEATURES)))
                base_real, base_str = p_real, p_str
            else:
                p_real, p_str = predict_q(f, Xn, scheme, lo, hi), predict_q(f, stress, scheme, lo, hi)
            if kind == "classifier":
                cls_real, cls_str = np.array(clf_classes)[p_real.argmax(1)], np.array(clf_classes)[p_str.argmax(1)]
                bcls_real, bcls_str = np.array(clf_classes)[base_real.argmax(1)], np.array(clf_classes)[base_str.argmax(1)]
                res[scheme] = {"train_accuracy_100_sites": round(float(accuracy_score(labels, cls_real)), 4),
                               "agreement_with_float64_10k_stress_pct": round(float((cls_str == bcls_str).mean() * 100), 2),
                               "max_abs_probability_change": round(float(np.abs(p_str - base_str).max()), 4)}
            else:
                res[scheme] = {"R2_on_100_sites_vs_labels": round(float(r2_score(y, p_real)), 5),
                               "max_abs_score_change_10k_stress_pts": round(float(np.abs(p_str - base_str).max()), 4),
                               "mean_abs_score_change_10k_stress_pts": round(float(np.abs(p_str - base_str).mean()), 5)}
        out[name] = res
    out["method"] = ("float32 / float16: thresholds, inputs and leaf values cast to that type. int16 / int8: per-feature affine "
                     "fixed point over the training range (thresholds rounded up so the <= test is preserved), leaf values int16. "
                     "Compared with the float64 scikit-learn model on the 100 real sites and on 10,000 random synthetic sites.")
    return out


# ----------------------------------------------------------------------------------------------------------- 4. offline data
def offline_storage() -> dict:
    span = 2 * hz.MAX_RANGE_M  # horizon rays reach 250 km in every direction
    crop = {}
    for res_m in (120, 240):
        px = math.ceil(span / res_m)
        crop[f"{res_m}m_px"] = {"pixels": f"{px} x {px}", "bytes_int16": px * px * 2, "MB": round(px * px * 2 / 1e6, 1)}
    local_patch = {"area": "2 km x 2 km around the landing point at 5 m/px (slope / hazard)", "bytes_int16": (2000 // 5) ** 2 * 2}
    prof = hz.N_AZ * 4
    eph_params = sum(len(v) for v in es.MODEL_PARAMS.values()) + 3  # + three periods
    return {
        "full_LOLA_polar_DEM_LDEM_75S_120M_MB": round(hz.DEM_PATH.stat().st_size / 1e6, 1) if hz.DEM_PATH.exists() else 116.3,
        "DEM_crop_for_horizon_250km_radius": crop,
        "local_terrain_patch": local_patch | {"KB": round(local_patch["bytes_int16"] / 1024, 1)},
        "precomputed_horizon_profile_per_site": {"directions": hz.N_AZ, "bytes_float32": prof, "bytes_int16_0p01deg": hz.N_AZ * 2,
                                                 "note": "if the horizon is computed on the ground before landing, the DEM is not needed on board for illumination at all"},
        "onboard_ephemeris_analytic_model": {
            "parameters": eph_params, "bytes_float64": eph_params * 8,
            "accuracy_vs_JPL_Horizons_deg_RMSE": {"sun": 0.067, "earth": 0.48},
            "validity": "fitted to the 60-day mission window; a longer mission needs re-fitted coefficients (uplinked) or "
                        "seasonal / libration terms",
            "source": "outputs/nasa_benchmark.json (308 real Horizons series)"},
        "onboard_ephemeris_table_alternative_estimate": {
            "layout": "Chebyshev polynomials of the sub-solar and sub-Earth latitude / longitude: 4 series x 10 coefficients x "
                      "float64 per 4-day segment (estimate; degree to be tuned against Horizons)",
            "bytes_per_year": int(365 / 4 * 4 * 10 * 8)},
        "illumination_maps_on_board": "not required: the stored horizon profile reproduces NASA's averages (benchmark error 1.5 pts)",
    }


# ----------------------------------------------------------------------------------------------------------- main
def main() -> dict:
    df, X, y, labels, reg, clf, unc = load()
    models = {"regressor_GradientBoosting": (reg, "gbr"), "classifier_RandomForest": (clf, "classifier"), "uncertainty_RandomForest": (unc, "rf")}
    EDGE_DIR.mkdir(parents=True, exist_ok=True)
    header_bytes = write_c_header(models, EDGE_DIR / "lunar_models.h")
    report = {
        "accuracy": accuracy(X, y, labels, reg, clf, unc),
        "footprint": footprint(models) | {"c_header_text_bytes": header_bytes, "c_header_path": "outputs/edge/lunar_models.h"},
        "compute": compute(models, X),
        "working_ram": working_ram(),
        "quantization": quantization(models, X, y, labels, list(clf.classes_)),
        "offline_storage": offline_storage(),
    }
    (OUTPUTS_DIR / "edge_profile.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    r = main()
    print(json.dumps(r, indent=1, default=str)[:12000])
