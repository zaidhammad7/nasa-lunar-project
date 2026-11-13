"""Physics-informed suitability scoring for lunar south-pole landing sites.

Pure computation (no UI / plotting imports). Shared by training and inference so
that labels and live predictions use exactly the same engineering rules.

Units: slope in degrees, elevation angles in degrees, visibility in percent.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CSV = REPO_ROOT / "final_lunar_dataset_fixed.csv"
MODELS_DIR = REPO_ROOT / "models"
OUTPUTS_DIR = REPO_ROOT / "outputs"
# Original features with real terrain shadowing applied (built by build_corrected_dataset.py); used for training,
# ranking and out-of-distribution checks. DATA_CSV itself is never modified.
TRAINING_CSV = OUTPUTS_DIR / "terrain_corrected_dataset.csv"

# Features fed to the ML models (Lat/Lon excluded: not physical drivers, and
# longitude is circular).
FEATURES = [
    "Sun_Visible_Pct", "Sun_Avg_El", "Sun_Max_El",
    "Earth_Visible_Pct", "Earth_Avg_El", "Earth_Max_El",
    "Elevation_m", "Slope_deg",
]
CLASSES = ["Hazardous", "Acceptable", "Optimal"]  # ordered worst -> best

# ---- Tunables -------------------------------------------------------------
W_TERRAIN, W_SOLAR, W_COMMS = 0.40, 0.35, 0.25
SLOPE_IDEAL_DEG = 5.0       # <= this: full terrain score
SLOPE_LIMIT_DEG = 15.0      # tip-over hazard limit
TERRAIN_AT_LIMIT = 50.0     # terrain score (0-100) exactly at the 15 deg limit
STEEP_PENALTY_PER_DEG = 5.0  # points lost per degree beyond the limit
SUN_MAX_EL_REF_DEG = 7.0    # solar max elevation giving full elevation credit
SUN_VIS_WEIGHT = 0.70       # remainder goes to Sun_Max_El
EARTH_AVG_EL_MIN_DEG = -6.0  # Earth avg elevation mapped to 0 credit
EARTH_AVG_EL_SPAN_DEG = 10.0  # ... and +4 deg maps to full credit
EARTH_VIS_WEIGHT = 0.70
OPTIMAL_MIN_SCORE, ACCEPTABLE_MIN_SCORE = 65.0, 45.0


def terrain_score(slope_deg, ideal_deg: float = SLOPE_IDEAL_DEG, limit_deg: float = SLOPE_LIMIT_DEG):
    """0-100 terrain safety: flat to `ideal_deg`, linear to `limit_deg`, steep beyond.

    Defaults (5 / 15 deg) are the training-label rules; pass a lander's own
    limits to recompute for a custom vehicle profile.
    """
    s = np.abs(np.asarray(slope_deg, dtype=float))
    mid = 100.0 - (100.0 - TERRAIN_AT_LIMIT) * (s - ideal_deg) / (limit_deg - ideal_deg)
    steep = TERRAIN_AT_LIMIT - STEEP_PENALTY_PER_DEG * (s - limit_deg)
    out = np.where(s <= ideal_deg, 100.0, np.where(s <= limit_deg, mid, steep))
    return np.clip(out, 0.0, 100.0)


def solar_score(sun_visible_pct, sun_max_el):
    """0-100 power/thermal score from illumination fraction and peak Sun elevation."""
    vis = np.clip(np.asarray(sun_visible_pct, dtype=float), 0, 100)
    el = np.clip(np.asarray(sun_max_el, dtype=float) / SUN_MAX_EL_REF_DEG, 0, 1) * 100.0
    return SUN_VIS_WEIGHT * vis + (1 - SUN_VIS_WEIGHT) * el


def comms_score(earth_visible_pct, earth_avg_el):
    """0-100 direct-to-Earth score from visibility fraction and mean Earth elevation."""
    vis = np.clip(np.asarray(earth_visible_pct, dtype=float), 0, 100)
    el = np.clip((np.asarray(earth_avg_el, dtype=float) - EARTH_AVG_EL_MIN_DEG) / EARTH_AVG_EL_SPAN_DEG, 0, 1) * 100.0
    return EARTH_VIS_WEIGHT * vis + (1 - EARTH_VIS_WEIGHT) * el


def suitability_score(df: pd.DataFrame) -> np.ndarray:
    """Composite Suitability_Score in [0, 100] (40% terrain, 35% solar, 25% comms)."""
    return (W_TERRAIN * terrain_score(df["Slope_deg"])
            + W_SOLAR * solar_score(df["Sun_Visible_Pct"], df["Sun_Max_El"])
            + W_COMMS * comms_score(df["Earth_Visible_Pct"], df["Earth_Avg_El"]))


def safety_class(slope_deg, score, ideal_deg: float = SLOPE_IDEAL_DEG, limit_deg: float = SLOPE_LIMIT_DEG):
    """Rule-based Safety_Class (vectorised): Optimal / Acceptable / Hazardous."""
    slope = np.abs(np.asarray(slope_deg, dtype=float))
    score = np.asarray(score, dtype=float)
    return np.where((slope <= ideal_deg) & (score >= OPTIMAL_MIN_SCORE), "Optimal",
                    np.where((slope <= limit_deg) & (score >= ACCEPTABLE_MIN_SCORE), "Acceptable", "Hazardous"))


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with component scores, Suitability_Score and Safety_Class."""
    out = df.copy()
    out["Terrain_Score"] = terrain_score(out["Slope_deg"])
    out["Solar_Score"] = solar_score(out["Sun_Visible_Pct"], out["Sun_Max_El"])
    out["Comms_Score"] = comms_score(out["Earth_Visible_Pct"], out["Earth_Avg_El"])
    out["Suitability_Score"] = suitability_score(out)
    out["Safety_Class"] = safety_class(out["Slope_deg"], out["Suitability_Score"])
    return out
