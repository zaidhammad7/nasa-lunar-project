# Lunar Landing Site Navigator - frontend (South Pole Mission Control)

React 19 + Vite + Tailwind 4 + three.js (`@react-three/fiber` / `drei`). Talks to the FastAPI backend in `../src/app`
(default `http://localhost:8000`, override with `VITE_API_URL`) and **falls back automatically** to a built-in offline engine
(100-site dataset + the calibrated 708.73 h Sun / 653.09 h + 661.31 h Earth physics) when the backend is unreachable.

## Run

```bash
# terminal 1 - backend (repo root)
uvicorn src.app.api_server:app --port 8000

# terminal 2 - frontend
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # production bundle in dist/
```

## What is where

| Folder | Role |
|---|---|
| `src/api/lunarModelApi.js` | fetch client + automatic offline fallback (422 validation errors are surfaced, outages are not) |
| `src/api/mockSimulationData.js`, `sitesData.json` | offline engine and the 100-site dataset (regenerate with `python scripts/build_sites_json.py`) |
| `src/lib/` | JS port of the backend physics, scoring and ranking (`physics.js`, `sites.js`), heatmap, battery survival, crater list |
| `src/hooks/` | `useLunarSimulation` (state, API calls), `useSolarPowerCalc` (instant tower / tilt / area maths), `useCsvExporter` |
| `src/components/scene3d/` | true-scale Moon (NASA CGI Moon Kit textures), Earth, Sun, star field, heatmap and crater layers, click picking, camera |
| `src/components/controls/` | location, priority, mission time, hardware, camera views, timeline, actions |
| `src/components/panels/` | results: decision, core metrics, countdowns, AI assessment, evidence, power survival, backup sites |
| `src/components/layout/`, `telemetry/` | dashboard shell, top bar, panel toggles, landing windows, comparison modal |

Moon textures: `python scripts/fetch_moon_kit.py` (NASA SVS CGI Moon Kit) writes `public/moon/`.

## Notes

* The 3-D scene is at true scale (1 unit = 1 Moon radius; Earth at 221 units, Sun at 86,105 units) with a logarithmic depth buffer.
* Optimisation mode re-weights the composite score (60/25/15, 40/35/25, 20/60/20). The GO / NO-GO safety verdict and the 13.5 deg
  safety factor are computed on the balanced score and never relaxed by the mode.
* Profiling switches: append `?perf=probe,noshadow,nolines,nostars,lowres` to the URL (`probe` logs JS time per frame in `window.__probe`).
