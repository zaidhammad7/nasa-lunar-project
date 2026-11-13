"""Self-test of every API function (no network server needed: uses FastAPI's TestClient).

    python src/app/api_selftest.py

Each check recomputes the expected value independently (NumPy / closed-form) and compares it
with what the API returned. Prints a verification report and writes outputs/api_selftest_report.json.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
os.environ["LUNAR_SKIP_BG_WARMUP"] = "1"  # the test must not start background network fetches
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import api_server  # noqa: E402
import ephemeris_series as es  # noqa: E402
import mission_simulator as ms  # noqa: E402
from suitability import OUTPUTS_DIR  # noqa: E402

RESULTS: list[dict] = []
T0 = es.BASELINE_START


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"test": name, "pass": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)
    return bool(ok)


def iso(h: float) -> str:
    return (T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def unit_vec(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def run() -> int:
    with TestClient(api_server.app) as client:
        # ---------------------------------------------------------------- health / CORS
        print("\n[0] Health, CORS")
        r = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
        hj = r.json()
        check("GET /api/health 200", r.status_code == 200, str(hj))
        check("health has models_ready, dem_ready, cached_demo_sites, safety_factor_active, warmup_latency_ms",
              {"status", "models_ready", "dem_ready", "cached_demo_sites", "safety_factor_active", "warmup_latency_ms"} <= set(hj)
              and hj["models_ready"] is True and hj["safety_factor_active"] is True and isinstance(hj["warmup_latency_ms"], float)
              and 0 <= hj["cached_demo_sites"] <= 5, f"warm-up {hj['warmup_latency_ms']} ms, {hj['cached_demo_sites']}/5 demo sites cached")
        check("CORS header allows any origin", r.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000"))

        # ---------------------------------------------------------------- /api/sites
        print("\n[1] GET /api/sites")
        r = client.get("/api/sites")
        js = r.json()
        check("returns 100 sites", r.status_code == 200 and js["n_sites"] == 100 and len(js["sites"]) == 100)
        check("top-5 list has <= 5 entries and ranked order", 1 <= len(js["top5_filtered"]) <= 5
              and [s["rank"] for s in js["top5_filtered"]] == sorted(s["rank"] for s in js["top5_filtered"]))
        q = {"max_slope_deg": 5, "min_sun_pct": 58, "min_earth_pct": 60, "lat": -86.0, "lon": 30.0}
        js = client.get("/api/sites", params=q).json()
        ok = all(s["slope_deg"] <= 5 and s["Sun_Visible_Pct"] >= 58 and s["Earth_Visible_Pct"] >= 60 for s in js["top5_filtered"])
        check("tight filters: every returned top-5 site satisfies all 3 constraints", ok and len(js["top5_filtered"]) > 0,
              f"{js['n_sites_passing_filters']} sites pass; top={[s['site_id'] for s in js['top5_filtered']]}")
        flagged = sum(s["passes_filters"] for s in js["sites"])
        check("passes_filters flags agree with n_sites_passing_filters", flagged == js["n_sites_passing_filters"])
        s0 = js["top5_filtered"][0]
        v1, v2 = unit_vec(-86.0, 30.0), unit_vec(s0["lat_deg"], s0["lon_deg_east"])
        d_ref = 1737.4 * math.acos(float(np.clip(v1 @ v2, -1, 1)))
        check("Haversine distance_km matches 3-D vector angle", abs(d_ref - s0["distance_km"]) < 0.01,
              f"{s0['distance_km']} km vs {d_ref:.3f} km")
        check("1 deg of latitude = 30.32 km", abs(float(ms.haversine_km(-90, 0, -89, 0)) - 1737.4 * math.pi / 180) < 1e-6)
        check("bearing: due south along meridian = 180 deg", abs(float(ms.initial_bearing_deg(-86, 30, -88, 30)) - 180) < 1e-6)
        check("bearing: due north along meridian = 0 deg", abs(float(ms.initial_bearing_deg(-88, 30, -86, 30)) % 360) < 1e-6)
        check("sites rejects out-of-range filter (422)", client.get("/api/sites", params={"max_slope_deg": 40}).status_code == 422)

        # ---------------------------------------------------------------- /api/evaluate (all 8 inputs)
        print("\n[2] POST /api/evaluate - preset site, all inputs")
        body = {"site_id": "Auto_SP_099", "start_datetime_utc": "2026-11-13T00:00:00Z", "duration_hours": 1440,
                "timeline_hour_index": 100, "max_slope_deg": 5, "min_sun_pct": 50, "min_earth_pct": 40,
                "tower_height_m": 20.0, "panel_tilt_deg": 88.0, "panel_area_m2": 12.5}
        t = time.perf_counter()
        r = client.post("/api/evaluate", json=body)
        dt = (time.perf_counter() - t) * 1000
        e = r.json()
        check("200 OK", r.status_code == 200, f"{dt:.0f} ms round trip incl. 1440-row timeline JSON")
        need = ["primary_landing_decision", "terrain_topography_physics", "solar_illumination_visibility",
                "earth_communication_status", "power_generation", "sunset_earthset_countdowns", "xai_and_hazard_alerts",
                "south_pole_map_and_top_5_sites", "top_3_landing_windows", "side_by_side_comparison", "csv_data_export", "timeline"]
        check("all dashboard output blocks present", all(k in e for k in need), str([k for k in need if k not in e]))
        p = e["primary_landing_decision"]
        check("#1 decision fields", all(k in p for k in ("Suitability_Score", "score_uncertainty_95ci", "Safety_Class",
                                                       "mission_status_label", "model_confidence_pct", "class_probabilities"))
              and 0 <= p["Suitability_Score"] <= 100 and 0 <= p["model_confidence_pct"] <= 100,
              f"{p['Suitability_Score']} {p['mission_status_label']} conf {p['model_confidence_pct']}%")
        ci = p["score_uncertainty_95ci"]
        check("#1 95% CI brackets the score", ci["lower"] <= p["Suitability_Score"] <= ci["upper"],
              f"[{ci['lower']}, {ci['upper']}] +/-{ci['plus_minus']}")
        check("#1 status label matches class", {"Optimal": "GO / Optimal", "Acceptable": "CONDITIONAL / Acceptable",
                                                 "Hazardous": "NO-GO / Hazardous"}[p["Safety_Class"]] == p["mission_status_label"])
        tt = e["terrain_topography_physics"]
        check("#2 terrain: slope, elevation, roughness", abs(tt["Slope_deg"] - 2.966) < 0.01 and tt["Elevation_m"] == -611.5
              and tt["Roughness_m"] is not None and tt["Roughness_m"] >= 0, str(tt))
        tl = e["timeline"]
        sun = np.array(tl["sun_el_eff_deg"])
        earth = np.array(tl["earth_el_eff_deg"])
        check("timeline has 1440 hourly rows", len(sun) == 1440 and tl["hour_index"][-1] == 1439 and len(tl["timestamp_utc"]) == 1440)
        boost = math.degrees(math.acos(1737400.0 / (1737400.0 + 20.0)))
        base = es.get_hourly_series(-85.3109, 332.293, ms._dataset().iloc[98].to_dict(), mode="auto")
        check("tower boost = acos(R/(R+h)) added to Sun elevation", np.allclose(sun, base.sun_el[:1440] + boost, atol=1e-3)
              and abs(e["scenario"]["hardware"]["tower_horizon_boost_deg"] - boost) < 1e-4, f"boost {boost:.5f} deg at 20 m")
        check("tower boost also applied to Earth", np.allclose(earth, base.earth_el[:1440] + boost, atol=1e-3))
        so = e["solar_illumination_visibility"]
        el_now = sun[100]
        exp_state = "Direct Sunlight" if el_now >= 0.265 else "Total Darkness" if el_now <= -0.265 else "Partial Shadow"
        check("#3 illumination_state follows the 0.265 deg disc rule", so["illumination_state"] == exp_state, f"el {el_now:.3f} -> {exp_state}")
        check("#3 mission-window Sun_Visible_Pct matches timeline", abs(so["Sun_Visible_Pct"] - (sun > 0).mean() * 100) < 0.01
              and abs(so["live_sun_elevation_deg"] - el_now) < 1e-3 and abs(so["Sun_Max_El"] - sun.max()) < 1e-2)
        states = np.array(tl["illumination_state"])
        exp_states = np.where(sun >= 0.265, "Direct Sunlight", np.where(sun <= -0.265, "Total Darkness", "Partial Shadow"))
        check("illumination state correct for all 1440 hours", bool((states == exp_states).all()),
              f"direct {int((states == 'Direct Sunlight').sum())}, partial {int((states == 'Partial Shadow').sum())}, dark {int((states == 'Total Darkness').sum())}")
        sun_x = base.sun_el[:1440] + boost  # unrounded elevations (the timeline carries 4 decimals, ~0.005 W of rounding)
        f = np.clip((sun_x + 0.265) / 0.53, 0, 1)
        P_ref = 1361.0 * 0.30 * 12.5 * f * np.maximum(0, np.sin(np.radians(sun_x + 88.0)))
        check("power per hour = S0*eta*A*f*max(0,sin(el+tilt))", np.allclose(np.array(tl["power_watts"]), P_ref, atol=2e-3),
              f"peak {P_ref.max():.1f} W, max |diff| {np.abs(np.array(tl['power_watts']) - P_ref).max():.5f} W")
        pg = e["power_generation"]
        check("#5 total energy = sum(P)/1000 kWh", abs(pg["total_accumulated_energy_kwh"] - P_ref.sum() / 1000) < 2e-3
              and abs(tl["cumulative_energy_kwh"][-1] - P_ref.sum() / 1000) < 2e-3, f"{pg['total_accumulated_energy_kwh']} kWh")
        check("#5 real-time/peak/average power", abs(pg["real_time_power_watts"] - P_ref[100]) < 0.01
              and abs(pg["peak_power_watts"] - P_ref.max()) < 0.01 and abs(pg["average_power_watts"] - P_ref.mean()) < 0.01)
        ec = e["earth_communication_status"]
        check("#4 DTE status matches Earth elevation", ec["dte_status"] == ("Connected (Line-of-Sight Clear)" if earth[100] > 0 else "Blocked (Signal Lost)")
              and abs(ec["Earth_Visible_Pct"] - (earth > 0).mean() * 100) < 0.01, f"{ec['dte_status']}, Earth el {earth[100]:.3f}")
        cd = e["sunset_earthset_countdowns"]
        ev = cd["time_to_sunrise"] if el_now <= 0 else cd["time_to_sunset"]
        if el_now <= 0:
            j = 100 + int(np.argmax(sun[100:] > 0))
        else:
            j = 100 + int(np.argmax(sun[100:] <= 0))
        a, b = sun[j - 1], sun[j]
        exp_h = (j - 1) + a / (a - b) - 100
        check("#6 sun countdown matches independent horizon crossing", ev is not None and abs(ev["hours"] - exp_h) < 0.01,
              f"{ev['formatted']} (expected {exp_h:.3f} h)")
        m = round(exp_h * 60)
        check("#6 formatted string 'Xd Xh Xm'", ev["formatted"] == f"{m // 1440}d {(m % 1440) // 60}h {m % 60}m", ev["formatted"])
        ek = cd["time_to_earthrise"] if earth[100] <= 0 else cd["time_to_earthset"]
        check("#6 earth countdown present", ek is not None and (ek["hours"] is not None or ek["note"]), str(ek))
        check("#6 only one of sunset/sunrise populated", (cd["time_to_sunset"] is None) != (cd["time_to_sunrise"] is None))
        xa = e["xai_and_hazard_alerts"]
        check("#7 justifications, warnings, component_scores", len(xa["justifications"]) >= 3 and isinstance(xa["warnings"], list)
              and set(xa["component_scores"]) == {"terrain", "solar", "comms"}, str(xa["component_scores"]))
        alt = e["south_pole_map_and_top_5_sites"]["top5_filtered"]
        check("#8 top-5 alternatives satisfy user filters and exclude the selected site",
              all(s["slope_deg"] <= 5 and s["Sun_Visible_Pct"] >= 50 and s["Earth_Visible_Pct"] >= 40 and s["site_id"] != "Auto_SP_099" for s in alt)
              and all("distance_km" in s and "bearing_deg" in s for s in alt), str([(s["site_id"], s["distance_km"], s["bearing_deg"]) for s in alt[:3]]))
        w = e["top_3_landing_windows"]["windows"]
        check("#9 returns up to 3 windows", 1 <= len(w) <= 3, f"{len(w)} window(s) for a 1440 h mission in a 1441 h baseline")
        check("#9 CSV metadata present", e["csv_data_export"]["row_count"] == 1440 and len(e["csv_data_export"]["columns"]) == 10)

        # ---------------------------------------------------------------- windows vs brute force
        print("\n[3] Top-3 landing windows vs brute force (240 h missions)")
        body2 = {"site_id": "Auto_SP_075", "duration_hours": 240, "tower_height_m": 10, "panel_tilt_deg": 80, "panel_area_m2": 20}
        e2 = client.post("/api/evaluate", json=body2).json()
        wins = e2["top_3_landing_windows"]["windows"]
        row = ms._dataset().set_index("Site_ID").loc["Auto_SP_075"].to_dict()
        row["Site_ID"] = "Auto_SP_075"
        ser = es.get_hourly_series(row["Lat"], row["Lon"], row, mode="auto")
        bo = ms.tower_boost_deg(10)
        se, ee = ser.sun_el + bo, ser.earth_el + bo
        Pw = ms.power_watts(se, 20, 80)
        L = 240
        best = []
        for s0_ in range(0, 1441 - L + 1):
            sl = slice(s0_, s0_ + L)
            best.append((s0_, Pw[sl].sum() / 1000, (se[sl] > 0).sum(), (ee[sl] > 0).sum()))
        emax = max(b[1] for b in best)
        obj = [0.4 * b[1] / emax + 0.3 * b[2] / L + 0.3 * b[3] / L for b in best]
        k = int(np.argmax(obj))
        check("#9 rank-1 window equals brute-force optimum", wins[0]["start_hour_index"] == best[k][0]
              and abs(wins[0]["energy_kwh"] - best[k][1]) < 2e-3, f"start {wins[0]['start_utc']}, {wins[0]['energy_kwh']} kWh")
        starts = [x["start_hour_index"] for x in wins]
        check("#9 windows are non-overlapping", all(abs(a_ - b_) >= L for i, a_ in enumerate(starts) for b_ in starts[i + 1:]), str(starts))
        check("#9 windows sorted by objective", [x["objective"] for x in wins] == sorted((x["objective"] for x in wins), reverse=True))
        check("#9 window length equals duration_hours", all(x["duration_hours"] == 240 for x in wins))

        # ---------------------------------------------------------------- custom coordinates / input forms
        print("\n[4] Custom coordinate, alternative input forms")
        t = time.perf_counter()
        r = client.post("/api/evaluate", json={"lat": -87.0, "lon": 100.0, "duration_days": 10,
                                                "timestamp_utc": "2026-11-15T06:00:00Z", "start_datetime_utc": "2026-11-13T00:00:00Z"})
        dt = (time.perf_counter() - t)
        ec_ = r.json()
        check("custom (lat, lon) evaluates without hanging (<= 3.6 s Horizons budget)", r.status_code == 200 and dt < 3.6,
              f"{dt:.2f} s; ephemeris source: {ec_.get('data_sources', {}).get('ephemeris')}")
        check("duration_days=10 -> 240 h and timestamp_utc -> hour 54", ec_["scenario"]["duration_hours"] == 240
              and ec_["scenario"]["timeline_hour_index"] == 54, str(ec_["scenario"]["timestamp_utc"]))
        check("custom point gets full output set", all(k in ec_ for k in need), f"terrain source: {ec_['terrain_topography_physics']['source']}")
        # Horizons slower than the budget -> analytic curve instantly, never a hang (fetch stubbed to be slow)
        real_fetch, real_budget = es.fetch_live, es.LIVE_BUDGET_S
        es.fetch_live = lambda lat, lon: (time.sleep(1.5), (_ for _ in ()).throw(RuntimeError("simulated slow Horizons")))[1]
        es.LIVE_BUDGET_S = 0.2
        try:
            t = time.perf_counter()
            s_fb = es.get_hourly_series(-86.4321, 77.1234, mode="auto")
            dt_fb = time.perf_counter() - t
        finally:
            es.fetch_live, es.LIVE_BUDGET_S = real_fetch, real_budget
        check("slow Horizons -> analytic fallback returned within budget (never hangs)", s_fb.source == "analytic_model"
              and dt_fb < 0.6 and len(s_fb.sun_el) == 1441 and any("did not answer" in n for n in s_fb.notes),
              f"{dt_fb * 1000:.0f} ms; note: {s_fb.notes[-1][:70]}...")
        near = client.post("/api/evaluate", json={"lat": -85.3109, "lon": 332.293, "duration_hours": 24}).json()
        check("coordinate equal to a preset snaps to that preset", near["scenario"]["site_id"] == "Auto_SP_099")

        # ---------------------------------------------------------------- guardrails through the API
        print("\n[5] Hard physics guardrails")
        r = client.post("/api/evaluate", json={"site_id": "Auto_SP_07", "duration_hours": 240}).json()
        pd_ = r["primary_landing_decision"]
        msg = "CRITICAL: Terrain slope exceeds 15° lander tip-over limit."
        check("slope > 15 deg -> Hazardous, score <= 35, exact warning", pd_["Safety_Class"] == "Hazardous"
              and pd_["Suitability_Score"] <= 35.0 and msg in r["xai_and_hazard_alerts"]["warnings"], f"{pd_['Suitability_Score']} {pd_['guardrails']}")
        ser99 = es.get_hourly_series(-85.3109, 332.293, mode="auto")
        b1 = ms.tower_boost_deg(1)
        dark_ok = [i for i in range(0, 1417) if (ser99.sun_el[i:i + 24] + b1 <= 0).all() and (ser99.earth_el[i:i + 24] + b1 > 0).all()]
        check("test setup: found a 24 h window with Sun fully dark and Earth visible", len(dark_ok) > 0, f"{len(dark_ok)} candidate starts")
        dark_start = dark_ok[len(dark_ok) // 2] if dark_ok else 0
        r = client.post("/api/evaluate", json={"site_id": "Auto_SP_099", "tower_height_m": 1, "start_datetime_utc": iso(dark_start),
                                                "duration_hours": 24}).json()
        pd_ = r["primary_landing_decision"]
        psr = "CRITICAL: Permanently Shadowed Region (PSR) risk — prolonged crater shadowing and extreme cryogenic hazard."
        check("Sun_Visible_Pct < 25 -> Hazardous, score <= 30, exact PSR warning", pd_["Safety_Class"] == "Hazardous"
              and pd_["Suitability_Score"] <= 30.0 and psr in r["xai_and_hazard_alerts"]["warnings"]
              and r["solar_illumination_visibility"]["Sun_Visible_Pct"] == 0.0, f"{pd_['Suitability_Score']} (raw ML {pd_['Suitability_Score_raw_ml']}) window start {iso(dark_start)}")
        check("ood_warning raised when a feature leaves the training range", r["xai_and_hazard_alerts"]["ood_warning"] is True,
              str(r["xai_and_hazard_alerts"]["ood_features"]))
        blk_ok = [i for i in range(0, 1417) if (ser99.earth_el[i:i + 24] + b1 <= 0).all() and (ser99.sun_el[i:i + 24] + b1 > 0.265).all()]
        check("test setup: found a 24 h window with Earth fully blocked and Sun fully lit", len(blk_ok) > 0, f"{len(blk_ok)} candidate starts")
        e_start = blk_ok[len(blk_ok) // 2] if blk_ok else 0
        r = client.post("/api/evaluate", json={"site_id": "Auto_SP_099", "tower_height_m": 1, "start_datetime_utc": iso(e_start),
                                                "duration_hours": 24}).json()
        pd_ = r["primary_landing_decision"]
        dte = "CRITICAL: Severe Direct-to-Earth (DTE) communication blackout."
        check("Earth_Visible_Pct < 10 -> Hazardous, score <= 35, exact DTE warning", pd_["Safety_Class"] == "Hazardous"
              and pd_["Suitability_Score"] <= 35.0 and dte in r["xai_and_hazard_alerts"]["warnings"]
              and pd_["guardrails"]["triggered"] == ["DTE_BLACKOUT"], f"{pd_['Suitability_Score']} {pd_['guardrails']['triggered']} window start {iso(e_start)}")
        healthy = client.post("/api/evaluate", json={"site_id": "Auto_SP_099"}).json()["primary_landing_decision"]
        check("healthy site: no guardrail, uncapped", healthy["guardrails"]["triggered"] == [] and healthy["Safety_Class"] == "Optimal",
              f"{healthy['Suitability_Score']} {healthy['mission_status_label']}")

        # ---------------------------------------------------------------- validation
        print("\n[6] Input validation")
        bad = [({"lat": -80, "lon": 10}, "lat outside -90..-85"), ({"lat": -86, "lon": 400}, "lon > 360"),
               ({"site_id": "Auto_SP_099", "tower_height_m": 25}, "tower > 20"), ({"site_id": "Auto_SP_099", "panel_tilt_deg": 120}, "tilt > 90"),
               ({"site_id": "Auto_SP_099", "panel_area_m2": 0.5}, "area < 1"), ({"site_id": "Auto_SP_099", "max_slope_deg": 20}, "slope > 15"),
               ({"site_id": "nope"}, "unknown site"), ({}, "no location"),
               ({"site_id": "Auto_SP_099", "start_datetime_utc": "2027-01-11T00:00:00Z", "duration_hours": 100}, "window past baseline"),
               ({"site_id": "Auto_SP_099", "duration_hours": 24, "timeline_hour_index": 24}, "timeline index outside window")]
        for payload, why in bad:
            check(f"422 for {why}", client.post("/api/evaluate", json=payload).status_code == 422)

        # ---------------------------------------------------------------- /api/compare
        print("\n[7] POST /api/compare (Scenario A vs Scenario B)")
        A = {"site_id": "Auto_SP_099", "duration_hours": 480, "tower_height_m": 1, "panel_tilt_deg": 45, "panel_area_m2": 10}
        B = {"site_id": "Auto_SP_075", "start_datetime_utc": "2026-12-01T00:00:00Z", "duration_hours": 480,
             "tower_height_m": 20, "panel_tilt_deg": 88, "panel_area_m2": 25}
        r = client.post("/api/compare", json={"scenario_a": A, "scenario_b": B})
        cmp_ = r.json()["side_by_side_comparison"]
        check("200 and both evaluations returned", r.status_code == 200 and "scenario_a" in cmp_ and "scenario_b" in cmp_
              and cmp_["scenario_a"]["scenario"]["site_id"] == "Auto_SP_099" and cmp_["scenario_b"]["scenario"]["site_id"] == "Auto_SP_075")
        dl = cmp_["deltas"]
        check("all required delta keys", {"delta_suitability_score", "delta_sunlight_hours", "delta_power_watts", "delta_energy_kwh",
                                          "delta_comms_uptime_pct", "delta_slope_deg"} <= set(dl), str(dl))
        ea = client.post("/api/evaluate", json=A).json()
        eb = client.post("/api/evaluate", json=B).json()
        ex = {"delta_suitability_score": eb["primary_landing_decision"]["Suitability_Score"] - ea["primary_landing_decision"]["Suitability_Score"],
              "delta_sunlight_hours": eb["solar_illumination_visibility"]["sunlight_hours"] - ea["solar_illumination_visibility"]["sunlight_hours"],
              "delta_power_watts": eb["power_generation"]["average_power_watts"] - ea["power_generation"]["average_power_watts"],
              "delta_energy_kwh": eb["power_generation"]["total_accumulated_energy_kwh"] - ea["power_generation"]["total_accumulated_energy_kwh"],
              "delta_comms_uptime_pct": eb["earth_communication_status"]["Earth_Visible_Pct"] - ea["earth_communication_status"]["Earth_Visible_Pct"],
              "delta_slope_deg": eb["terrain_topography_physics"]["Slope_deg"] - ea["terrain_topography_physics"]["Slope_deg"]}
        tol = {"delta_suitability_score": 0.011, "delta_sunlight_hours": 1e-6, "delta_power_watts": 0.02, "delta_energy_kwh": 0.01,
               "delta_comms_uptime_pct": 0.01, "delta_slope_deg": 0.002}
        check("deltas equal (B - A) of the two standalone evaluations", all(abs(dl[k] - ex[k]) <= tol[k] for k in tol),
              ", ".join(f"{k.replace('delta_', 'd_')}={dl[k]:+.3f}" for k in tol))
        r = client.post("/api/compare", json={"scenario_a": A, "scenario_b": A})
        z = r.json()["side_by_side_comparison"]["deltas"]
        check("identical scenarios -> all deltas exactly 0", all(abs(v) < 1e-9 for v in z.values()), str(z))

        # ---------------------------------------------------------------- /api/export-csv
        print("\n[8] POST /api/export-csv")
        csv_body = {"site_id": "Auto_SP_099", "duration_hours": 300, "start_datetime_utc": "2026-11-20T00:00:00Z",
                    "tower_height_m": 8, "panel_tilt_deg": 70, "panel_area_m2": 15}
        r = client.post("/api/export-csv", json=csv_body)
        check("200, text/csv, attachment filename", r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
              and "mission_telemetry_export.csv" in r.headers.get("content-disposition", ""), r.headers.get("content-disposition", ""))
        rows = list(csv.reader(io.StringIO(r.text)))
        hdr = rows[0]
        check("exact column list", hdr == ["timestamp_utc", "hour_index", "illumination_state", "sun_el_eff_deg", "dte_status",
                                           "earth_el_eff_deg", "time_to_sunset_hrs", "time_to_earthset_hrs", "power_watts",
                                           "cumulative_energy_kwh"], str(hdr))
        data = rows[1:]
        check("one row per mission hour (300)", len(data) == 300 and data[0][0] == "2026-11-20T00:00:00Z" and data[-1][1] == "299")
        cum = np.array([float(x[9]) for x in data])
        pw = np.array([float(x[8]) for x in data])
        el = np.array([float(x[3]) for x in data])
        check("cumulative energy monotone and equals sum(P)/1000", bool((np.diff(cum) >= -1e-9).all()) and abs(cum[-1] - pw.sum() / 1000) < 5e-3,
              f"{cum[-1]:.3f} kWh")
        ev = client.post("/api/evaluate", json=csv_body).json()
        check("CSV total energy equals /api/evaluate total", abs(cum[-1] - ev["power_generation"]["total_accumulated_energy_kwh"]) < 5e-3)
        ts = np.array([float(x[6]) if x[6] else np.nan for x in data])
        i = int(np.argmax(el > 0))
        ok_ts = True
        for idx in range(len(el) - 1):
            if el[idx] > 0 and el[idx + 1] <= 0 and not np.isnan(ts[idx]):  # sunset between idx and idx+1
                ok_ts = ok_ts and 0 < ts[idx] <= 1.0001
        check("time_to_sunset_hrs <= 1 h on the row before a sunset; decreases while lit", ok_ts
              and all(ts[k + 1] < ts[k] for k in range(len(ts) - 1) if el[k] > 0 and el[k + 1] > 0 and not np.isnan(ts[k]) and not np.isnan(ts[k + 1])))
        states = {x[2] for x in data}
        check("illumination_state values are valid", states <= {"Direct Sunlight", "Partial Shadow", "Total Darkness"}, str(states))
        check("dte_status values are valid", {x[4] for x in data} <= {"Connected (Line-of-Sight Clear)", "Blocked (Signal Lost)"})

        # ---------------------------------------------------------------- /api/stress-test
        print("\n[9] GET /api/stress-test")
        r = client.get("/api/stress-test")
        if r.status_code == 200:
            js = r.json()
            check("returns stress_test + cross_validation", "stress_test" in js and js["cross_validation"] is not None
                  and "regressors" in js["cross_validation"], f"CV regressors: {list(js['cross_validation']['regressors'])}")
            check("stress-test summary exposes the four panel verdicts", {"panel1_all_pass", "panel2_zero_fatal_errors", "panel3_all_pass",
                                                                           "panel4_sites_per_second"} <= set(js["stress_test"]["summary"]))
        else:
            check("stress-test results available", False, "run src/analysis/stress_test.py first")

        # ---------------------------------------------------------------- safety factor + warm-up
        print("\n[9b] 3-layer safety factor")
        r = client.post("/api/evaluate", json={"site_id": "Auto_SP_33", "duration_hours": 240}).json()
        pdx, sf = r["primary_landing_decision"], r["primary_landing_decision"]["safety_factor"]
        check("14.7 deg site (below 15 deg limit) -> NO-GO via 13.5 deg operational limit",
              pdx["Safety_Class"] == "Hazardous" and pdx["mission_status_label"] == "NO-GO / Hazardous"
              and "SLOPE_DERATING" in sf["layers_triggered"] and sf["operational_slope_limit_deg"] == 13.5
              and abs(sf["factor_of_safety"] - 15 / 13.5) < 1e-3, f"score {pdx['Suitability_Score']} (before SF {sf['score_before_safety_factor']}, {sf['class_before_safety_factor']})")
        check("margin warning/justification present", any("13.5" in w and "safety margin" in w for w in r["xai_and_hazard_alerts"]["warnings"])
              and any("Safety factor SLOPE_DERATING" in j for j in r["xai_and_hazard_alerts"]["justifications"]))
        check("Hazardous verdict never shows an Acceptable-looking score (<= 44)", pdx["Suitability_Score"] <= 44.0)
        r2_ = client.post("/api/evaluate", json={"site_id": "Auto_SP_33", "duration_hours": 240, "max_slope_deg": 10}).json()["primary_landing_decision"]["safety_factor"]
        check("derating follows the user's max_slope_deg (10 -> 8.5 deg)", r2_["operational_slope_limit_deg"] == 8.5 and abs(r2_["factor_of_safety"] - 10 / 8.5) < 1e-3)
        ds_ = ms._dataset()
        near = ds_[(ds_["Slope_deg"] > 13.5) & (ds_["Slope_deg"] <= 15.0)]["Site_ID"].tolist()
        bad_n = [s_ for s_ in near if client.post("/api/evaluate", json={"site_id": s_, "duration_hours": 240}).json()["primary_landing_decision"]["Safety_Class"] != "Hazardous"]
        check("every dataset site with 13.5 < slope <= 15 deg is NO-GO", len(near) > 0 and not bad_n, f"{len(near)} sites: {near}")
        js = client.get("/api/sites").json()
        check("/api/sites top-5 respects the derated slope limit", all(s_["slope_deg"] <= 13.5 for s_ in js["top5_filtered"]) and js["filters"]["effective_max_slope_deg"] == 13.5, str(js["filters"]))
        # asymmetric classifier threshold: lower it knowingly and confirm the override logic with a probe
        import pandas as pd
        import predict_site as ps_
        probe = ps_._dataset()[ps_.FEATURES].head(20).copy()
        out_ = ps_.predict_batch(probe)
        flip = (out_["p_hazardous"] >= 0.28) & (out_["Safety_Class"] != "Hazardous")
        check("P(Hazardous) >= 0.28 always yields Hazardous (20 probe sites)", not bool(flip.any()))
        sc_, cl_, m_ = ps_.apply_safety_factor(probe.head(3).assign(Slope_deg=[2.0, 2.0, 2.0]), [46.9, 52.0, 70.0], ["Acceptable"] * 3,
                                               [0.0] * 3, [0.5, 5.0, 0.5], 15.0)
        check("SCORE_BUFFER: 46.9 (<48) and 52 with +/-5 CI (lower 47) -> ok only if both bounds hold",
              list(m_["SCORE_BUFFER"]) == [True, False, False] and list(cl_) == ["Hazardous", "Acceptable", "Acceptable"], f"classes {list(cl_)}")
        sc2, cl2, m2 = ps_.apply_safety_factor(probe.head(2).assign(Slope_deg=[2.0, 2.0]), [60.0, 60.0], ["Acceptable"] * 2, [0.2, 0.2], [0.5, 20.0], 15.0)
        check("SCORE_BUFFER: wide CI (lower bound 40 < 45) demotes a score-60 site", list(m2["SCORE_BUFFER"]) == [False, True], f"classes {list(cl2)}")
        sc3, cl3, m3 = ps_.apply_safety_factor(probe.head(2).assign(Slope_deg=[2.0, 2.0]), [60.0, 60.0], ["Acceptable"] * 2, [0.279, 0.28], [0.5, 0.5], 15.0)
        check("HAZARD_PROB threshold: 0.279 stays, 0.28 flips to Hazardous", list(cl3) == ["Acceptable", "Hazardous"], f"classes {list(cl3)}")
        sc4, cl4, m4 = ps_.apply_safety_factor(probe.head(2).assign(Slope_deg=[12.9, 12.9]), [60.0, 60.0], ["Acceptable"] * 2, [0.0, 0.0], [0.5, 0.5], 15.0, [0.0, 4.0])
        check("roughness clause: slope 12.9 + 0.5*4 m = 14.9 ok, but + 0.5*5 > 15 would flip; 12.9 vs 13.5 limit passes",
              list(m4["SLOPE_DERATING"]) == [False, False])
        sc5, cl5, m5 = ps_.apply_safety_factor(probe.head(1).assign(Slope_deg=[13.0]), [60.0], ["Acceptable"], [0.0], [0.5], 15.0, [5.0])
        check("roughness clause: slope 13.0 + 0.5*5 = 15.5 > 15 -> SLOPE_DERATING", bool(m5["SLOPE_DERATING"][0]) and cl5[0] == "Hazardous")

        print("\n[9c] Warm-up")
        t = time.perf_counter()
        r = client.post("/api/warmup")
        wj = r.json()
        check("POST /api/warmup 200 with 5 demo sites", r.status_code == 200 and len(wj["sites"]) == 5, f"{(time.perf_counter() - t):.1f} s total (DEM open included)")
        check("warm-up reports cache status + eval latency per site", all({"fully_cached", "eval_hot_ms", "eval_cold_ms", "series_source", "Safety_Class"} <= set(s_) for s_ in wj["sites"]),
              ", ".join(f"{s_['key']}:{s_['eval_hot_ms']}ms" for s_ in wj["sites"]))
        check("warm-up: all 5 demo sites served from cache", wj["cached_demo_sites"] == 5 and all(s_["fully_cached"] for s_ in wj["sites"]))
        check("warm-up opened the LOLA DEM (dem_ready) or reported why not", wj["dem_ready"] is True or ("error" in wj["dem"]), str(wj["dem"])[:140])
        h2 = client.get("/api/health").json()
        check("health after warm-up: dem_ready mirrors warm-up, 5/5 cached", h2["cached_demo_sites"] == 5 and h2["dem_ready"] == wj["dem_ready"], str({k: h2[k] for k in ("dem_ready", "cached_demo_sites", "response_cache_entries")}))
        r = client.post("/api/evaluate", json={"site_id": "Auto_SP_46"})
        check("demo A first request served from the pre-computed response cache (X-Cache: HIT)", r.headers.get("x-cache") == "HIT",
              f"{r.elapsed.total_seconds() * 1000:.0f} ms")
        r = client.post("/api/evaluate", json={"lat": -89.54, "lon": 197.0})
        check("custom demo site E (cached terrain + series) is a cache HIT", r.headers.get("x-cache") == "HIT" and r.json()["data_sources"]["terrain"] != "")
        r = client.post("/api/evaluate", json={"site_id": "Auto_SP_46", "tower_height_m": 7.5})
        check("changed parameters miss the cache and are computed correctly", r.headers.get("x-cache") == "MISS" and r.json()["scenario"]["hardware"]["tower_height_m"] == 7.5)

        print("\n[9d] Optimisation priority modes")
        ev = {m: client.post("/api/evaluate", json={"site_id": "Auto_SP_099", "priority_mode": m, "duration_hours": 240}).json()
              for m in ("most_safety", "balanced", "most_power")}
        pdm = {m: ev[m]["primary_landing_decision"] for m in ev}
        check("mode weights are 60/25/15, 40/35/25, 20/60/20", pdm["most_safety"]["mode_weights"] == {"terrain": 0.6, "solar": 0.25, "comms": 0.15}
              and pdm["balanced"]["mode_weights"] == {"terrain": 0.4, "solar": 0.35, "comms": 0.25}
              and pdm["most_power"]["mode_weights"] == {"terrain": 0.2, "solar": 0.6, "comms": 0.2})
        cs = ev["balanced"]["xai_and_hazard_alerts"]["component_scores"]
        exp_shift = {"most_safety": (0.6 - 0.4) * cs["terrain"] + (0.25 - 0.35) * cs["solar"] + (0.15 - 0.25) * cs["comms"],
                     "most_power": (0.2 - 0.4) * cs["terrain"] + (0.6 - 0.35) * cs["solar"] + (0.2 - 0.25) * cs["comms"]}
        ok_shift = all(abs((pdm[m]["Suitability_Score"] - pdm["balanced"]["Suitability_Score"]) - exp_shift[m]) < 0.02 for m in exp_shift)
        check("score = balanced score + change of the weighted composite (flat site: safety > balanced > power)", ok_shift
              and pdm["most_safety"]["Suitability_Score"] > pdm["balanced"]["Suitability_Score"] > pdm["most_power"]["Suitability_Score"],
              ", ".join(f"{m} {pdm[m]['Suitability_Score']}" for m in pdm))
        check("safety verdict is identical in every mode", len({pdm[m]["Safety_Class"] for m in pdm}) == 1 and
              len({pdm[m]["Suitability_Score_balanced"] for m in pdm}) == 1)
        hz = {m: client.post("/api/evaluate", json={"site_id": "Auto_SP_33", "priority_mode": m, "duration_hours": 240}).json()["primary_landing_decision"] for m in ("most_safety", "most_power")}
        check("MOST POWER cannot relax a NO-GO: derated-slope site stays Hazardous and <= 44", all(v["Safety_Class"] == "Hazardous" and v["Suitability_Score"] <= 44.0 for v in hz.values()), str({m: v["Suitability_Score"] for m, v in hz.items()}))
        sj = {m: client.get("/api/sites", params={"priority_mode": m}).json() for m in ("most_safety", "balanced", "most_power")}
        check("/api/sites re-ranks per mode (ranks 1..100 unique, top-5 sorted by mode score)", all(
            sorted(s_["rank"] for s_ in sj[m]["sites"]) == list(range(1, 101))
            and [x["Suitability_Score"] for x in sj[m]["top5_filtered"]] == sorted((x["Suitability_Score"] for x in sj[m]["top5_filtered"]), reverse=True) for m in sj))
        check("top-5 list differs between MOST SAFETY and MOST POWER", [x["site_id"] for x in sj["most_safety"]["top5_filtered"]] != [x["site_id"] for x in sj["most_power"]["top5_filtered"]]
              or [x["Suitability_Score"] for x in sj["most_safety"]["top5_filtered"]] != [x["Suitability_Score"] for x in sj["most_power"]["top5_filtered"]],
              str({m: [x["site_id"] for x in sj[m]["top5_filtered"]] for m in sj}))
        check("sites carry display_class with the 13.5 deg derating (no site >13.5 deg is coloured safe)",
              all(s_["Safety_Class"] == "Hazardous" for s_ in sj["balanced"]["sites"] if s_["slope_deg"] > 13.5))
        check("unknown priority_mode -> 422", client.post("/api/evaluate", json={"site_id": "Auto_SP_099", "priority_mode": "yolo"}).status_code == 422
              and client.get("/api/sites", params={"priority_mode": "yolo"}).status_code == 422)
        cmp_m = client.post("/api/compare", json={"scenario_a": {"site_id": "Auto_SP_099", "priority_mode": "most_safety"},
                                                  "scenario_b": {"site_id": "Auto_SP_099", "priority_mode": "most_power"}}).json()["side_by_side_comparison"]
        check("compare honours per-scenario priority_mode", cmp_m["scenario_a"]["primary_landing_decision"]["priority_mode"] == "most_safety"
              and cmp_m["scenario_b"]["primary_landing_decision"]["priority_mode"] == "most_power" and cmp_m["deltas"]["delta_suitability_score"] < 0)

        # ---------------------------------------------------------------- latency
        print("\n[10] Latency")
        lat = []
        for h in range(0, 400, 20):
            t = time.perf_counter()
            client.post("/api/evaluate", json={**body, "timeline_hour_index": h})
            lat.append((time.perf_counter() - t) * 1000)
        check("preset /api/evaluate incl. 1440-row timeline: median < 250 ms", float(np.median(lat)) < 250,
              f"median {np.median(lat):.0f} ms, p95 {np.percentile(lat, 95):.0f} ms")
        t = time.perf_counter()
        for _ in range(20):
            es.calibrated_series(-85.0, 183.0, ms._dataset().iloc[43].to_dict())
        check("hourly series generator < 50 ms", (time.perf_counter() - t) / 20 * 1000 < 50,
              f"{(time.perf_counter() - t) / 20 * 1000:.2f} ms")

    n_pass = sum(r_["pass"] for r_ in RESULTS)
    print(f"\n==== API SELF-TEST: {n_pass}/{len(RESULTS)} checks passed ====")
    for r_ in RESULTS:
        if not r_["pass"]:
            print("  FAILED:", r_["test"], "-", r_["detail"])
    OUTPUTS_DIR.mkdir(exist_ok=True)
    (OUTPUTS_DIR / "api_selftest_report.json").write_text(json.dumps(
        {"generated_utc": datetime.now(timezone.utc).isoformat(), "passed": n_pass, "total": len(RESULTS), "checks": RESULTS}, indent=2))
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(run())
