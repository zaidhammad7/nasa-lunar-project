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
| `src/api/mockSimulationData.js`, `sitesData.json` | offline engine and the 100-site dataset |
| `src/lib/physics.js`, `sites.js` | JS port of the backend physics / scoring / ranking (verified identical to `/api/sites`) |
| `src/hooks/` | `useLunarSimulation` (state, debounced API calls), `useSolarPowerCalc` (instant tower / tilt / area maths), `useCsvExporter` |
| `src/components/scene3d/` | Moon (procedural cratered relief), Sun + Earth, rays, fly-to camera, click raycasting |
| `src/components/controls/` | the 9 input controls |
| `src/components/telemetry/`, `layout/` | KPI ribbon, telemetry drawers, XAI, windows, comparison |

## Notes

* The 3-D Sun / Earth distances are stylised (not to scale) so both stay in frame; their *directions* come from the physics model.
* Optimisation mode re-weights the composite score (60/25/15, 40/35/25, 20/60/20). The GO / NO-GO safety verdict and the 13.5 deg
  safety factor are computed on the balanced score and never relaxed by the mode.
* Profiling switches: append `?perf=probe,noshadow,nolines,nostars,lowres` to the URL (`probe` logs JS time per frame in `window.__probe`).
