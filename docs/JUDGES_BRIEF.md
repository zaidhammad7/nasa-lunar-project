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
3. **Real terrain shadowing:** NASA LOLA's measured average Sun and Earth visibility (60 m/px, 2009–2013) sets each point's
   *effective horizon* — how high the surrounding crater walls stand — and every hourly elevation is measured above it.
   So sunlight, power, battery, countdowns and the verdict all reflect real shadowing, for presets and clicked points alike.
4. **Machine learning:** a model trained on the 100 sites (terrain-shadowed features) predicts the suitability score
   (gradient boosting; 5-fold cross-validated error **≈ 3.7 points** out of 100, R² = 0.95).
5. **Three-layer safety factor.** A site is NO-GO if any layer fails:
   - Slope must be under the lander limit minus a 1.5° margin (15° → **13.5°**), including a roughness allowance.
   - The *worst-case* score (95% lower bound) must clear the acceptance threshold plus a 3-point buffer.
   - The model's probability of "hazardous" must be under **28%**.
   - Hard rules also force NO-GO for sunlight below 25% of the time, Earth contact below 10%, or slope above 15°.
6. **Priority modes** (Most Safety / Balanced / Most Power) re-weight terrain, solar and comms, but **never relax the safety verdict**.

## Why you can trust the numbers
- **100-case data and system suite** passes: dataset integrity, derived-file consistency, physics, safety rules, API, input validation, and browser-vs-backend parity.
- **107 automated API checks** pass; each recomputes the expected value independently (including terrain shadowing).
- **23 tower-range checks** pass: the horizon gain matches the exact geometry (acos(R/(R+h))), sunlight never decreases with height, and the verdict is never degraded by a taller mast.
- The **offline engine** in the browser mirrors the backend, so the app works without internet.
- Out-of-range inputs are flagged ("outside model training range") instead of silently extrapolated.

## Validation against real NASA measurements — and the fix
We compared our first model with NASA LRO LOLA **terrain-shadowed** illumination maps (`python src/analysis/validate_illumination.py`).
The map reading was verified first: six known permanently shadowed craters (Shackleton, Haworth, Faustini…) all read 0% sunlight.

| Sunlight, 100 sites | Before (smooth horizon) | After (NASA terrain shadowing) |
|---|---|---|
| Mean, ours vs NASA | 66% vs 21% | 21% vs 21% |
| Average error | **45 points** (no correlation, r = −0.25) | **0.02 points** |
| Earth visibility error | 21 points (r = 0.54) | 0.02 points |

The first model could not see crater walls, so it gave every site about 60% sunlight; in reality half the sites are lit less
than 20% of the time. After the fix, the picture is honest: **2 Optimal, 41 Acceptable, 57 NO-GO** sites. The best sites
survive the correction — **Auto_SP_075** (50% Sun, 78% Earth, 4.8° slope) and **Auto_SP_099** (35% Sun, 56% Earth, 3.0° slope).
Shackleton's floor reads 0% sunlight and NO-GO, even with a 150 m mast.

*Note:* after the fix the long-run averages match NASA **by construction** (the horizon is fitted to NASA's value), so the
"after" column is a consistency check, not an independent test. What remains approximate is hour-by-hour timing.

## Honest limits
- **One horizon height in every direction:** averages match NASA, but the timing of individual sunrises and sunsets is approximate (a full horizon profile from the elevation model would fix this).
- NASA's averages cover **2009–2013**; our timeline covers a 60-day window (Nov 2026 – Jan 2027), scaled so its average matches.
- The heatmap is **interpolated** from 100 scored sites. Only clicked points get a full evaluation.
- Terrain for custom points comes from a **118 m/px** elevation model; a 20 m/px polar model would resolve smaller hazards.
- Crater names mark crater **centres**, not NASA's exact Artemis III region boundaries.

## Next steps
Full horizon profiles from the elevation model (exact sunrise/sunset times) · higher-resolution polar terrain · water-ice proximity (permanently shadowed regions) · landing-ellipse scoring · traverse planning.
