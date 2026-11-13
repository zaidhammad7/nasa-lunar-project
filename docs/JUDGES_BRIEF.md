# Lunar Landing Site Navigator — Judges' Brief
**NASA Space Apps 2026 · Team TNB · Lunar South Pole (−85° to −90°)**

## The problem
Artemis is going to the lunar South Pole for water ice. The terrain there is steep, the Sun barely clears the horizon,
and Earth often drops out of view. A good landing site has to be flat enough to land on, lit long enough to power the
lander, and in view of Earth often enough to talk to it. Our tool scores all three, for any point, at any time.

## What it does
| Feature | What you see | Why it matters |
|---|---|---|
| **Real NASA Moon** | 3-D Moon at true scale (Moon, Earth and Sun at real sizes and distances), textured with NASA's CGI Moon Kit (LRO LROC colour + LOLA elevation) | Planners see the real South Pole, not an artist's sphere |
| **Click anywhere** | Any point in the cap is evaluated live at its exact coordinates | Not limited to a preset list |
| **Landing decision** | Score 0–100, GO / CONDITIONAL / NO-GO, 95% confidence interval | One clear answer, with its uncertainty |
| **Evidence card** | Every safety check, with the measured value next to its limit | Judges and planners can audit *why* — no black box |
| **Suitability heatmap** | Whole cap coloured by score (green = better), updates with the priority mode | The best regions are visible at a glance |
| **Named craters** | Shackleton, de Gerlache, Haworth, Faustini, Nobile, Malapert… (IAU coordinates) | Several Artemis III candidate regions are named after these features |
| **Mission timeline** | Sun and Earth move hour by hour over 60 days, with live countdowns to sunrise and Earthrise | Landing timing matters as much as location |
| **Power survival** | Battery charge simulated through the longest lunar night, plus the minimum battery needed | Answers "will the lander survive the night?" |
| **Hardware what-if** | Tower height (1–150 m), panel tilt and area update power instantly | A taller mast sees over the horizon: 150 m gains 0.75° of Sun elevation |
| **Compare + export** | Side-by-side comparison of two sites; CSV mission summary | Ready for a planning review |

## How it works
1. **Terrain:** slope, elevation and roughness from the NASA LRO **LOLA** digital elevation model.
2. **Sun and Earth:** hourly positions from **JPL Horizons** (Sun = 10, Earth = 399, seen from the Moon = 301), with a calibrated analytic fallback when offline.
3. **Machine learning:** a model trained on 100 South Pole sites predicts the suitability score (gradient boosting; 5-fold cross-validated error **≈ 2 points** out of 100, R² = 0.97).
4. **Three-layer safety factor.** A site is NO-GO if any layer fails:
   - Slope must be under the lander limit minus a 1.5° margin (15° → **13.5°**), including a roughness allowance.
   - The *worst-case* score (95% lower bound) must clear the acceptance threshold plus a 3-point buffer.
   - The model's probability of "hazardous" must be under **28%**.
5. **Priority modes** (Most Safety / Balanced / Most Power) re-weight terrain, solar and comms, but **never relax the safety verdict**.

## Why you can trust the numbers
- **107 automated API checks** pass (physics, validation, caching, latency: median 17 ms per evaluation).
- **23 tower-range checks** pass: the horizon gain matches the exact geometry (acos(R/(R+h))), sunlight never decreases with height, and the verdict is never degraded by a taller mast.
- The **offline engine** in the browser mirrors the backend, so the demo works without internet.
- Out-of-range inputs are flagged ("outside model training range") instead of silently extrapolated.

## Honest limits
- The heatmap is **interpolated** from 100 scored sites. Only clicked points get a full evaluation.
- Sun and Earth visibility use a **smooth-horizon** model: local crater-rim shadowing is not yet ray-traced from the elevation model.
- Terrain for custom points comes from a **118 m/px** elevation model; a 20 m/px polar model would resolve smaller hazards.
- Crater names mark crater **centres**, not NASA's exact Artemis III region boundaries.

## Next steps
Horizon ray-tracing from the elevation model · higher-resolution polar terrain · water-ice proximity (permanently shadowed regions) · landing-ellipse scoring · traverse planning.
