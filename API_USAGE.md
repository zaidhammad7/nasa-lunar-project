# Lunar Landing Site Navigator - API quick start

Start the server from the repo root:

```bash
pip install -r requirements.txt
uvicorn src.app.api_server:app --port 8000
```

Interactive docs: http://localhost:8000/docs

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status, DEM readiness |
| GET | `/api/sites` | 100 preset sites + Top 5 passing `max_slope_deg`, `min_sun_pct`, `min_earth_pct` |
| POST | `/api/evaluate` | One scenario: decision, terrain, Sun/Earth, power, countdowns, alerts, top-3 windows, hourly timeline |
| POST | `/api/compare` | `{scenario_a, scenario_b}` with exact deltas (B - A) |
| POST | `/api/export-csv` | Hourly telemetry as `mission_telemetry_export.csv` |
| GET | `/api/stress-test` | Stress-test results + cross-validation metrics |

## Example

```bash
curl -X POST http://localhost:8000/api/evaluate -H "Content-Type: application/json" -d '{
  "site_id": "Auto_SP_099",
  "duration_hours": 1440,
  "timeline_hour_index": 100,
  "max_slope_deg": 5, "min_sun_pct": 50, "min_earth_pct": 40,
  "tower_height_m": 10, "panel_tilt_deg": 80, "panel_area_m2": 20
}'
```

Use `lat` (-90 to -85) and `lon` (0 to 360) instead of `site_id` for a custom point.

## Verify

```bash
python src/analysis/train_and_evaluate.py   # models + figures
python src/analysis/stress_test.py          # 4-panel stress test
python src/app/api_selftest.py              # 77 API checks
```
