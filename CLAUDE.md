# Lunar Landing Site Navigator — NASA Space Apps 2026 (Team TNB)

## Goal
Help mission planners evaluate and rank candidate lunar landing sites by combining terrain
safety (slope, roughness) with illumination/Earth-visibility timelines, shown in an interactive
3D Streamlit dashboard.

## Architecture
```
data/            DEM grids (GeoTIFF/NPY/CSV) and ephemeris CSVs. Raw downloads are git-ignored.
src/analysis/    Pure computation: ephemeris, illumination, slope/roughness, site scoring.
src/app/         Streamlit UI only: loads data, calls src/analysis, renders Plotly 3D.
requirements.txt Python dependencies.
```

### Rules
- `src/analysis` must not import `streamlit` or `plotly`; it stays testable and UI-free.
- `src/app` contains no scientific logic — call `src/analysis` functions.
- Data loading/caching lives in one place (`@st.cache_data` wrappers in the app, plain functions in analysis).
- Never commit large raw data; document how to fetch it (script or README note) instead.
- Run the app from the repo root: `streamlit run src/app/main.py`.

## Coding standards
- Python 3.10+, PEP 8, type hints on public functions, docstrings with units (m, deg, km, UTC).
- Use NumPy vectorization over loops; DEMs are 2D arrays with explicit pixel size (m/px).
- Coordinates: selenographic lat/lon in degrees; times as UTC `astropy.time.Time`.
- No hard-coded absolute paths; use `pathlib` relative to the repo root.
- Keep functions small and deterministic; put tunables (slope limit, weights) in named constants.
- Secrets/keys via environment variables, never committed.

## NASA data references
- **LRO Quickmap** — https://quickmap.lroc.asu.edu/ : LOLA/LROC layers, slopes, illumination, DEM exports.
- **NASA Moon Trek** — https://trek.nasa.gov/moon/ : DEM/imagery tiles via WMTS and download tools.
- **JPL Horizons** — https://ssd.jpl.nasa.gov/horizons/ (API: https://ssd.jpl.nasa.gov/api/horizons.api):
  Sun (`10`) and Earth (`399`) ephemerides as seen from the Moon (`301`) for illumination and Earth visibility.

## Scoring outline
1. Slope (from DEM) and roughness → hazard mask (typical lander limit ≈ 5–10°).
2. Sun elevation timeline → illumination fraction and longest shadow/dark periods.
3. Earth elevation → communications line-of-sight fraction.
4. Weighted composite score per cell/site; weights configurable in the dashboard.
