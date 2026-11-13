"""Pre-pitch readiness check: run this ~1 minute before the live demo.

    python src/app/warmup_demo.py                    # full check (fetches anything missing, ~1-2 min on a cold cache)
    python src/app/warmup_demo.py --url http://localhost:8000   # also check the running API server
    python src/app/warmup_demo.py --no-live          # never touch the network (caches only)

It verifies the LOLA DEM connection, fills ./ephemeris_cache/ for the 5 golden demo sites, runs a
Scenario A vs B comparison and a CSV export, checks the safety factor, and prints a checklist with
millisecond latencies. Exit code 0 = READY FOR LIVE DEMO.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
os.system("")  # enables ANSI colours in the Windows console

import demo_sites  # noqa: E402
import mission_simulator as ms  # noqa: E402
import predict_site as ps  # noqa: E402

G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m"
CHECKS: list[tuple[str, str, str]] = []  # (status, label, detail)


def step(status: str, label: str, detail: str = "") -> None:
    colour = {"OK": G, "WARN": Y, "FAIL": R}[status]
    mark = {"OK": "✔", "WARN": "!", "FAIL": "✘"}[status]
    CHECKS.append((status, label, detail))
    print(f" {colour}{mark}{X} {label:<58s} {detail}", flush=True)


def timed(fn, *a, **k):
    t = time.perf_counter()
    out = fn(*a, **k)
    return out, (time.perf_counter() - t) * 1000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="base URL of a running API server to check as well")
    ap.add_argument("--no-live", action="store_true", help="do not use the network (caches only)")
    a = ap.parse_args()
    t_all = time.perf_counter()
    lat: dict[str, float] = {}
    print(f"\n{B}Lunar Landing Site Navigator - live-demo readiness check{X}\n")

    # 1 ---------------------------------------------------------------- models + batch inference
    try:
        def load():
            ps._load_models(); ps._uncertainty_model(); ms._ranked(); ms._roughness_table()
            return ps.predict_batch(ps._dataset()[ps.FEATURES].head(64))
        out, ms_ = timed(load)
        lat["models + ranked CSV + dummy batch"] = ms_
        step("OK", "Models, ranked CSV loaded; batch inference warm", f"{ms_:7.0f} ms  ({len(out)} rows)")
    except Exception as exc:
        step("FAIL", "Models / ranked CSV", f"{type(exc).__name__}: {exc}")

    # 2 ---------------------------------------------------------------- LOLA DEM
    dem_ok = False
    if a.no_live:
        step("WARN", "LOLA DEM connection", "skipped (--no-live)")
    else:
        try:
            info, ms_ = timed(ps.warm_dem)
            dem_ok = True
            lat["DEM open + 3x3 read"] = ms_
            step("OK", "LOLA DEM open + 3x3 read at (-88.3448, 225.8806)",
                 f"{ms_:7.0f} ms  (open {info['open_ms']:.0f}, read {info['read_ms']:.0f}; elev {info['elevation_m']} m, slope {info['slope_deg']} deg)")
        except Exception as exc:
            step("WARN", "LOLA DEM connection failed", f"{type(exc).__name__}: {str(exc)[:80]} - terrain caches will be used")

    # 3 ---------------------------------------------------------------- demo sites
    print(f"\n {B}Golden demo sites{X}")
    sites_ok = True
    for s in demo_sites.DEMO_SITES:
        try:
            r = demo_sites.warm_site(s, allow_live=not a.no_live)
            lat[f"demo {s['key']} evaluation (hot)"] = r["eval_hot_ms"]
            cached = r["series_cached"] and r["terrain_cached"]
            sites_ok &= cached
            detail = (f"{r['eval_hot_ms']:6.1f} ms hot / {r['eval_cold_ms']:.0f} ms cold | {r['mission_status_label']:<24s} "
                      f"score {r['Suitability_Score']:5.1f} | slope {r['Slope_deg']:5.1f} sun {r['Sun_Visible_Pct']:5.1f}% earth {r['Earth_Visible_Pct']:5.1f}%"
                      + (f" | fetched in {r['cache_fill_ms']:.0f} ms" if r["cache_fill_ms"] > 50 else ""))
            if cached:
                step("OK", f"[{s['key']}] {s['name'][:50]}", detail)
            else:
                step("FAIL", f"[{s['key']}] {s['name'][:50]} - NOT cached", "; ".join(r["errors"]) or "series/terrain missing")
        except Exception as exc:
            sites_ok = False
            step("FAIL", f"[{s['key']}] {s['name'][:50]}", f"{type(exc).__name__}: {str(exc)[:80]}")
    n_cached = demo_sites.cached_count()
    step("OK" if n_cached == 5 else "FAIL", "ephemeris_cache populated for all demo sites", f"{n_cached}/5 sites fully cached")

    # 4 ---------------------------------------------------------------- Scenario A vs B
    print()
    try:
        sa, sb = demo_sites.demo_scenario(demo_sites.DEMO_SITES[0]), demo_sites.demo_scenario(demo_sites.DEMO_SITES[1], tower_height_m=15.0, panel_tilt_deg=85.0, panel_area_m2=20.0)
        cmp_, ms_ = timed(ms.compare_scenarios, sa, sb)
        d = cmp_["side_by_side_comparison"]["deltas"]
        lat["Scenario A vs B comparison"] = ms_
        step("OK", "Scenario A vs Scenario B comparison", f"{ms_:7.1f} ms  (d_score {d['delta_suitability_score']:+.2f}, d_energy {d['delta_energy_kwh']:+.0f} kWh, d_comms {d['delta_comms_uptime_pct']:+.1f}%)")
    except Exception as exc:
        step("FAIL", "Scenario A vs B comparison", f"{type(exc).__name__}: {exc}")

    # 5 ---------------------------------------------------------------- CSV export
    try:
        text, ms_ = timed(ms.build_csv, demo_sites.demo_scenario(demo_sites.DEMO_SITES[0]))
        rows = len(text.splitlines()) - 1
        lat["CSV export (1440 h)"] = ms_
        step("OK" if rows == 1440 else "FAIL", "CSV export of the full 1,440 h mission", f"{ms_:7.1f} ms  ({rows} rows, {len(text) / 1024:.0f} KB)")
    except Exception as exc:
        step("FAIL", "CSV export", f"{type(exc).__name__}: {exc}")

    # 6 ---------------------------------------------------------------- safety factor
    try:
        r, ms_ = timed(ms.evaluate_scenario, ms.Scenario(site_id="Auto_SP_33"), False, "auto", False, False)
        d = r["primary_landing_decision"]
        ok = d["Safety_Class"] == "Hazardous" and "SLOPE_DERATING" in d["safety_factor"]["layers_triggered"]
        lat["safety-factor evaluation"] = ms_
        step("OK" if ok else "FAIL", "3-layer safety factor active (14.7 deg site -> NO-GO)", f"{ms_:7.1f} ms  (layers: {', '.join(d['safety_factor']['layers_triggered'])}; limit {d['safety_factor']['operational_slope_limit_deg']} deg)")
    except Exception as exc:
        step("FAIL", "Safety factor check", f"{type(exc).__name__}: {exc}")

    # 6b --------------------------------------------------------------- PSR guardrail demo window
    try:
        import numpy as np
        import ephemeris_series as es
        site = ps._dataset().set_index("Site_ID").loc["Auto_SP_099"]
        ser = es.get_hourly_series(float(site["Lat"]), float(site["Lon"]), site.to_dict(), mode="auto")
        b1 = ms.tower_boost_deg(1.0)
        ok_starts = [i for i in range(0, 1417) if (ser.sun_el[i:i + 24] + b1 <= 0).all() and (ser.earth_el[i:i + 24] + b1 > 0).all()]
        start = ok_starts[len(ok_starts) // 2]
        when = (es.BASELINE_START + es.timedelta(hours=start)).strftime("%Y-%m-%dT%H:%M:%SZ")
        scn = ms.Scenario(site_id="Auto_SP_099", start_datetime_utc=es.BASELINE_START + es.timedelta(hours=start), duration_hours=24, tower_height_m=1.0)
        r, ms_ = timed(ms.evaluate_scenario, scn, False, "auto", False, False)
        d = r["primary_landing_decision"]
        ok = "PSR" in d["guardrails"]["triggered"] and d["Safety_Class"] == "Hazardous" and d["Suitability_Score"] <= 30
        lat["PSR guardrail demo window"] = ms_
        step("OK" if ok else "FAIL", "PSR guardrail demo: Auto_SP_099, 24 h dark window", f"{ms_:7.1f} ms  (start {when}, tower 1 m -> {d['mission_status_label']}, score {d['Suitability_Score']})")
    except Exception as exc:
        step("FAIL", "PSR guardrail demo window", f"{type(exc).__name__}: {exc}")

    # 7 ---------------------------------------------------------------- optional: running server
    if a.url:
        try:
            import requests
            h, ms_ = timed(lambda: requests.get(a.url.rstrip("/") + "/api/health", timeout=5).json())
            lat["API /api/health"] = ms_
            ok = h.get("models_ready") and h.get("safety_factor_active")
            step("OK" if ok else "FAIL", f"API server health ({a.url})", f"{ms_:7.1f} ms  (dem_ready {h.get('dem_ready')}, cached_demo_sites {h.get('cached_demo_sites')}/5, warm-up {h.get('warmup_latency_ms')} ms)")
            body = demo_sites.request_body(demo_sites.DEMO_SITES[0])
            _, ms_ = timed(lambda: requests.post(a.url.rstrip("/") + "/api/evaluate", json=body, timeout=30))
            lat["API /api/evaluate (demo A)"] = ms_
            step("OK", "API /api/evaluate for demo site A", f"{ms_:7.1f} ms")
        except Exception as exc:
            step("FAIL", f"API server at {a.url}", f"{type(exc).__name__}: {str(exc)[:80]}")

    # ------------------------------------------------------------------ summary
    print(f"\n {B}Latency summary{X}")
    for k, v in lat.items():
        print(f"   {k:<42s} {v:9.1f} ms")
    fails = [c for c in CHECKS if c[0] == "FAIL"]
    warns = [c for c in CHECKS if c[0] == "WARN"]
    print(f"\n total check time {(time.perf_counter() - t_all):.1f} s | {len(CHECKS) - len(fails) - len(warns)} ok, {len(warns)} warnings, {len(fails)} failures")
    if not fails:
        print(f"\n {G}{B}======================================={X}\n {G}{B}   READY FOR LIVE DEMO{X}\n {G}{B}======================================={X}\n")
        return 0
    print(f"\n {R}{B}NOT READY - fix:{X} " + "; ".join(c[1] for c in fails) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
