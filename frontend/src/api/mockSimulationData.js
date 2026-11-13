// Offline fallback engine: the pre-loaded 100-site dataset + the calibrated analytic physics (708.73 h synodic
// Sun cycle, 653.09 h / 661.31 h Earth libration) so every panel keeps working when the FastAPI backend is down.
// It returns the same response shape as the backend; ML-only fields (model confidence, class probabilities)
// are null and the score is the rule-based composite (flagged via data_sources / _source = "offline").
import {
  N_SAMPLES, BASELINE_START_MS, HOUR_MS, analyticSeries, calibrate, horizonFor, towerBoostDeg, sunDiscFraction, stateCode, STATE_NAMES,
  powerWatts, nextEvent, components, compositeScore, MODES, terrainScore, effectiveMaxSlope, ROUGHNESS_WEIGHT, SCORE_BUFFER,
  ACCEPTABLE_MIN, SAFETY_CAP, DEFAULT_MIN_SUN, DEFAULT_MIN_EARTH, SLOPE_MARGIN_DEG, DTE_CONNECTED, DTE_BLOCKED, iso, clamp, MODE_KEYS,
} from '../lib/physics.js'
import { SITES, siteById, nearestPreset, rankSites, idw } from '../lib/sites.js'

export { SITES }
const CI_HALF = 4.0 // 1.96 x cross-validated RMSE (2.05 pts)
const err422 = (msg) => Object.assign(new Error(msg), { status: 422 })
const cache = new Map()

function series(lat, lon, site) {
  const key = site ? site.id : `${lat.toFixed(3)},${lon.toFixed(3)}`
  if (cache.has(key)) return cache.get(key)
  const a = analyticSeries(lat, lon)
  const s = site
    ? { sun: calibrate(a.sun, site.sun, site.sunAvg, site.sunMax), earth: calibrate(a.earth, site.earth, site.earthAvg, site.earthMax), calibrated: true }
    : (() => { // custom point: terrain shadowing from NASA-measured visibility interpolated from the nearby sites
        const hs = horizonFor(a.sun, idw(lat, lon, 'sun')), he = horizonFor(a.earth, idw(lat, lon, 'earth'))
        return { sun: a.sun.map((v) => v - hs), earth: a.earth.map((v) => v - he), calibrated: false }
      })()
  cache.set(key, s)
  return s
}

const longestRun = (arr, pred) => { let b = 0, c = 0; for (const v of arr) { c = pred(v) ? c + 1 : 0; if (c > b) b = c } return b }

function bestWindows(sunEff, earthEff, L, area, tilt) {
  const lit = new Float64Array(N_SAMPLES + 1), dte = new Float64Array(N_SAMPLES + 1), P = new Float64Array(N_SAMPLES + 1), joint = new Float64Array(N_SAMPLES + 1)
  for (let i = 0; i < N_SAMPLES; i++) {
    const l = sunEff[i] > 0 ? 1 : 0, d = earthEff[i] > 0 ? 1 : 0
    lit[i + 1] = lit[i] + l; dte[i + 1] = dte[i] + d; joint[i + 1] = joint[i] + l * d; P[i + 1] = P[i] + powerWatts(sunEff[i], area, tilt)
  }
  const starts = [], rows = []
  for (let s = 0; s + L <= N_SAMPLES; s++) {
    const e = (P[s + L] - P[s]) / 1000
    rows.push({ s, sun: lit[s + L] - lit[s], dte: dte[s + L] - dte[s], joint: joint[s + L] - joint[s], e })
    starts.push(s)
  }
  const emax = Math.max(...rows.map((r) => r.e), 1e-9)
  rows.forEach((r) => { r.obj = 0.4 * (r.e / emax) + 0.3 * (r.sun / L) + 0.3 * (r.dte / L) })
  const chosen = []
  for (const r of [...rows].sort((a, b) => b.obj - a.obj)) {
    if (chosen.every((c) => Math.abs(c.s - r.s) >= L)) chosen.push(r)
    if (chosen.length === 3) break
  }
  return chosen.map((r, i) => ({
    rank: i + 1, start_utc: iso(BASELINE_START_MS + r.s * HOUR_MS), end_utc: iso(BASELINE_START_MS + (r.s + L) * HOUR_MS),
    start_hour_index: r.s, duration_hours: L, sunlight_hours: r.sun, dte_uptime_hours: r.dte,
    dte_uptime_pct: (r.dte / L) * 100, simultaneous_sun_and_dte_hours: r.joint, energy_kwh: r.e,
    average_power_watts: (r.e * 1000) / L, objective: r.obj,
  }))
}

/** Offline evaluation with the same response shape as POST /api/evaluate. */
export function offlineEvaluate(body) {
  const t0 = performance.now()
  const mode = body.priority_mode || 'balanced'
  if (!MODES[mode]) throw err422(`unknown priority_mode '${mode}'`)
  const preset = body.site_id ? siteById(body.site_id) : body.lat != null && body.lon != null ? nearestPreset(body.lat, body.lon) : null
  if (body.site_id && !preset) throw err422(`unknown site_id '${body.site_id}'`)
  if (!preset && (body.lat == null || body.lon == null)) throw err422('provide site_id or lat and lon')
  const lat = preset ? preset.lat : body.lat, lon = preset ? preset.lon : ((body.lon % 360) + 360) % 360
  if (lat < -90 || lat > -85) throw err422('lat outside [-90, -85]')

  const startMs = body.start_datetime_utc ? Date.parse(body.start_datetime_utc) : BASELINE_START_MS
  const startIdx = Math.round((startMs - BASELINE_START_MS) / HOUR_MS)
  const L = Math.round(body.duration_hours ?? 1440)
  if (!(startIdx >= 0 && startIdx < N_SAMPLES)) throw err422('start_datetime_utc must lie within the 2026-11-13..2027-01-12 window')
  if (L < 1 || startIdx + L > N_SAMPLES) throw err422(`mission window exceeds the ephemeris baseline; max duration from this start is ${N_SAMPLES - startIdx} h`)
  const idx = body.timeline_hour_index ?? 0
  if (idx < 0 || idx >= L) throw err422(`timeline index ${idx} outside the mission window [0, ${L - 1}]`)

  const tower = body.tower_height_m ?? 5, tilt = body.panel_tilt_deg ?? 45, area = body.panel_area_m2 ?? 10
  const maxSlope = body.max_slope_deg ?? 15, minSun = body.min_sun_pct ?? DEFAULT_MIN_SUN, minEarth = body.min_earth_pct ?? DEFAULT_MIN_EARTH
  const boost = towerBoostDeg(tower)
  const ser = series(lat, lon, preset)
  const sunEff = ser.sun.map((v) => v + boost), earthEff = ser.earth.map((v) => v + boost)
  const sunW = sunEff.subarray(startIdx, startIdx + L), earthW = earthEff.subarray(startIdx, startIdx + L)
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length
  const f = {
    sunPct: (sunW.filter((v) => v > 0).length / L) * 100, sunAvg: mean(sunW), sunMax: Math.max(...sunW),
    earthPct: (earthW.filter((v) => v > 0).length / L) * 100, earthAvg: mean(earthW), earthMax: Math.max(...earthW),
  }
  const slope = preset ? preset.slope : idw(lat, lon, 'slope')
  const elevation = preset ? preset.elev : idw(lat, lon, 'elev')
  const rough = preset ? preset.rough : null

  // ---- scoring + hard guardrails + safety factor (rule-based stand-in for the ML score)
  const comp = components(slope, f.sunPct, f.sunMax, f.earthPct, f.earthAvg)
  const ruleBal = compositeScore(comp, 'balanced')
  const ruleMode = compositeScore(comp, mode)
  const mlClass = slope <= 5 && ruleBal >= 65 ? 'Optimal' : slope <= 15 && ruleBal >= ACCEPTABLE_MIN ? 'Acceptable' : 'Hazardous'
  const guards = []
  if (slope > 15) guards.push(['TIP_OVER', 35, 'CRITICAL: Terrain slope exceeds 15Â° lander tip-over limit.'])
  if (f.sunPct < 25) guards.push(['PSR', 30, 'CRITICAL: Sun visible less than 25% of the time (terrain shadowing) — long dark periods and extreme cold; permanently shadowed region risk.'])
  if (f.earthPct < 10) guards.push(['DTE_BLACKOUT', 35, 'CRITICAL: Severe Direct-to-Earth (DTE) communication blackout.'])
  const eff = effectiveMaxSlope(maxSlope)
  const layers = []
  if (slope > eff || slope + ROUGHNESS_WEIGHT * (rough || 0) > maxSlope) layers.push('SLOPE_DERATING')
  if (ruleBal < ACCEPTABLE_MIN + SCORE_BUFFER || ruleBal - CI_HALF < ACCEPTABLE_MIN) layers.push('SCORE_BUFFER')
  const safety = guards.length || layers.length || mlClass === 'Hazardous' ? 'Hazardous' : mlClass
  const caps = guards.map((g) => g[1]).concat(safety === 'Hazardous' ? [SAFETY_CAP] : [])
  const cap = caps.length ? Math.min(...caps) : null
  const score = cap != null ? Math.min(ruleMode, cap) : ruleMode

  const warnings = guards.map((g) => g[2])
  if (layers.includes('SLOPE_DERATING')) warnings.push(`WARNING: Slope ${slope.toFixed(1)}Â° exceeds the ${eff.toFixed(1)}Â° operational limit (${maxSlope.toFixed(1)}Â° tip-over limit minus the ${SLOPE_MARGIN_DEG}Â° safety margin for DEM uncertainty, FSâ‰ˆ${(maxSlope / Math.max(eff, 1e-9)).toFixed(2)}); NO-GO.`)
  if (layers.includes('SCORE_BUFFER')) warnings.push(`WARNING: Score ${ruleBal.toFixed(1)} is inside the ${SCORE_BUFFER}-pt safety buffer of the ${ACCEPTABLE_MIN} Acceptable threshold; treated as Hazardous.`)
  const dark = longestRun(sunW, (v) => v <= 0), blackout = longestRun(earthW, (v) => v <= 0)
  if (dark > 100) warnings.push(`Prolonged crater shadowing: longest continuous Sun outage ${dark} h in this window.`)
  if (blackout > 150) warnings.push(`Comms blackout risk: longest continuous Earth outage ${blackout} h in this window.`)
  warnings.push('Offline mode: rule-based estimate with calibrated analytic physics (backend unreachable).')
  const flags = [
    ...guards.map((g) => ({ code: `GUARDRAIL_${g[0]}`, severity: 'CRITICAL', message: g[2] })),
    ...layers.map((l) => ({ code: `SAFETY_FACTOR_${l}`, severity: 'CRITICAL', message: l === 'SLOPE_DERATING' ? `Slope ${slope.toFixed(1)}Â° above the ${eff.toFixed(1)}Â° operational limit` : 'Score inside the safety buffer' })),
    ...(f.sunPct < minSun ? [{ code: 'LOW_SUN_AVAILABILITY', severity: 'WARNING', message: `Sun visible ${f.sunPct.toFixed(0)}% < required ${minSun}%.` }] : []),
    ...(f.earthPct < minEarth ? [{ code: 'LOW_EARTH_LINK', severity: 'WARNING', message: `Earth visible ${f.earthPct.toFixed(0)}% < required ${minEarth}%.` }] : []),
    ...(dark > 100 ? [{ code: 'LONG_DARKNESS', severity: 'WARNING', message: `Longest continuous Sun outage ${dark} h - size batteries/thermal for survival.` }] : []),
    { code: 'OFFLINE_FALLBACK', severity: 'WARNING', message: 'Backend unreachable: using the built-in analytic fallback.' },
  ]
  const readiness = flags.some((x) => x.severity === 'CRITICAL') ? 'NO-GO' : flags.some((x) => x.severity === 'WARNING') ? 'CAUTION' : 'GO'
  const just = [
    slope <= 5 ? `Terrain: slope ${slope.toFixed(1)}Â° is within the ideal â‰¤5Â° envelope for touchdown stability.` : slope <= 15 ? `Terrain: slope ${slope.toFixed(1)}Â° is acceptable (â‰¤15Â°) but erodes tip-over margin.` : `Terrain: slope ${slope.toFixed(1)}Â° exceeds the 15Â° lander tip-over limit.`,
    `Power/thermal: Sun above horizon ${f.sunPct.toFixed(0)}% of the window (max elevation ${f.sunMax.toFixed(1)}Â°).`,
    `Comms: Earth visible ${f.earthPct.toFixed(0)}% of the window (mean elevation ${f.earthAvg.toFixed(1)}Â°).`,
    `Overall classification: ${safety}.`,
  ]

  // ---- hourly timeline for the mission window
  const P = new Float64Array(L), cum = new Float64Array(L), disc = new Float64Array(L), states = new Array(L), dteS = new Array(L), ts = new Array(L)
  let acc = 0
  for (let i = 0; i < L; i++) {
    P[i] = powerWatts(sunW[i], area, tilt); acc += P[i] / 1000; cum[i] = acc; disc[i] = sunDiscFraction(sunW[i])
    states[i] = STATE_NAMES[stateCode(sunW[i])]; dteS[i] = earthW[i] > 0 ? DTE_CONNECTED : DTE_BLOCKED
    ts[i] = iso(startMs + i * HOUR_MS)
  }
  const abs = startIdx + idx
  const sunEv = nextEvent(sunEff, abs), earthEv = nextEvent(earthEff, abs)
  const top = rankSites({ mode, maxSlope, minSun, minEarth }, { lat, lon }, preset?.id).top5
  const lowerBound = Math.max(0, score - CI_HALF)
  const num = (v, d = 3) => Math.round(v * 10 ** d) / 10 ** d
  return {
    schema_version: 'offline-1', _source: 'offline',
    scenario: { lat_deg: lat, lon_deg_east: lon, site_id: preset?.id ?? null, is_preset_site: !!preset, start_datetime_utc: iso(startMs),
      end_datetime_utc: iso(startMs + L * HOUR_MS), duration_hours: L, timeline_hour_index: idx, timestamp_utc: iso(startMs + idx * HOUR_MS),
      priority_mode: mode, vehicle: { max_slope_deg: maxSlope, min_sun_pct: minSun, min_earth_pct: minEarth },
      hardware: { tower_height_m: tower, tower_horizon_boost_deg: boost, panel_tilt_deg: tilt, panel_area_m2: area } },
    primary_landing_decision: {
      Suitability_Score: num(score, 2), score_uncertainty_95ci: { lower: num(lowerBound, 2), upper: num(Math.min(100, score + CI_HALF, cap ?? 100), 2), plus_minus: CI_HALF, method: 'offline: 1.96 x CV RMSE' },
      Safety_Class: safety, mission_status_label: { Optimal: 'GO / Optimal', Acceptable: 'CONDITIONAL / Acceptable', Hazardous: 'NO-GO / Hazardous' }[safety],
      model_confidence_pct: null, class_probabilities: null, Suitability_Score_raw_ml: null,
      guardrails: { triggered: guards.map((g) => g[0]), score_cap: guards.length ? Math.min(...guards.map((g) => g[1])) : null },
      safety_factor: { active: true, layers_triggered: layers, operational_slope_limit_deg: eff, mechanical_slope_limit_deg: maxSlope, slope_safety_margin_deg: SLOPE_MARGIN_DEG, factor_of_safety: eff > 0 ? num(maxSlope / eff, 3) : null },
      priority_mode: mode, mode_weights: { terrain: MODES[mode].w[0], solar: MODES[mode].w[1], comms: MODES[mode].w[2] }, Suitability_Score_balanced: num(ruleBal, 2),
      mission_readiness: readiness, ood_warning: false,
    },
    terrain_topography_physics: { Slope_deg: num(slope), Elevation_m: num(elevation, 1), Roughness_m: rough == null ? null : num(rough), source: preset ? 'dataset (LOLA DEM, offline copy)' : 'dataset IDW interpolation (fallback)' },
    solar_illumination_visibility: { illumination_state: states[idx], sun_disc_fraction: num(disc[idx], 4), Sun_Visible_Pct: num(f.sunPct), live_sun_elevation_deg: num(sunW[idx], 4), Sun_Max_El: num(f.sunMax), Sun_Avg_El: num(f.sunAvg), sunlight_hours: sunW.filter((v) => v > 0).length, longest_dark_hours: dark, tower_horizon_boost_deg: boost, ephemeris_source: ser.calibrated ? 'analytic_calibrated' : 'analytic_model' },
    earth_communication_status: { dte_status: dteS[idx], Earth_Visible_Pct: num(f.earthPct), live_earth_elevation_deg: num(earthW[idx], 4), Earth_Max_El: num(f.earthMax), Earth_Avg_El: num(f.earthAvg), longest_blackout_hours: blackout },
    power_generation: { real_time_power_watts: num(P[idx], 2), peak_power_watts: num(Math.max(...P), 2), average_power_watts: num(mean(P), 2), total_accumulated_energy_kwh: num(acc, 3), accumulated_energy_to_current_hour_kwh: num(cum[idx], 3) },
    sunset_earthset_countdowns: { from_timestamp_utc: iso(BASELINE_START_MS + abs * HOUR_MS), time_to_sunset: sunEv.currently_above_horizon ? sunEv : null, time_to_sunrise: sunEv.currently_above_horizon ? null : sunEv, time_to_earthset: earthEv.currently_above_horizon ? earthEv : null, time_to_earthrise: earthEv.currently_above_horizon ? null : earthEv },
    xai_and_hazard_alerts: {
      justifications: just, warnings, component_scores: { terrain: num(comp.terrain, 2), solar: num(comp.solar, 2), comms: num(comp.comms, 2) }, hazard_flags: flags,
      confidence: { level: 'LOW', score_interval_95: [num(lowerBound, 2), num(score + CI_HALF, 2)], live_data: false }, ood_warning: false, ood_features: [],
      explanation: { weights: { terrain: MODES[mode].w[0], solar: MODES[mode].w[1], comms: MODES[mode].w[2] },
        weighted_contributions_pts: { terrain: num(MODES[mode].w[0] * comp.terrain, 2), solar: num(MODES[mode].w[1] * comp.solar, 2), comms: num(MODES[mode].w[2] * comp.comms, 2) },
        points_lost_by_component: { terrain: num(MODES[mode].w[0] * (100 - comp.terrain), 2), solar: num(MODES[mode].w[1] * (100 - comp.solar), 2), comms: num(MODES[mode].w[2] * (100 - comp.comms), 2) },
        feature_sensitivity_pts: {} },
    },
    south_pole_map_and_top_5_sites: { top5_filtered: top.map((s) => ({ rank: s.rankInMode, site_id: s.id, lat_deg: s.lat, lon_deg_east: s.lon, Suitability_Score: s.modeScore, Safety_Class: s.displayClass, slope_deg: s.slope, Sun_Visible_Pct: s.sun, Earth_Visible_Pct: s.earth, distance_km: s.distanceKm, bearing_deg: s.bearing })) },
    top_3_landing_windows: { windows: bestWindows(sunEff, earthEff, L, area, tilt) },
    csv_data_export: { endpoint: '/api/export-csv', filename: 'mission_telemetry_export.csv', row_count: L },
    timeline: { timestamp_utc: ts, hour_index: Array.from({ length: L }, (_, i) => i), illumination_state: states, sun_disc_fraction: Array.from(disc), sun_el_eff_deg: Array.from(sunW), dte_status: dteS, earth_el_eff_deg: Array.from(earthW), power_watts: Array.from(P), cumulative_energy_kwh: Array.from(cum) },
    data_sources: { ephemeris: 'offline analytic fallback', terrain: preset ? 'offline dataset copy' : 'offline IDW (fallback)' },
    compute_ms: Math.round((performance.now() - t0) * 10) / 10,
  }
}

export function offlineCompare(a, b) {
  const ea = offlineEvaluate(a), eb = offlineEvaluate(b)
  const g = (e) => ({ score: e.primary_landing_decision.Suitability_Score, sun: e.solar_illumination_visibility.sunlight_hours, p: e.power_generation.average_power_watts, pk: e.power_generation.peak_power_watts, e: e.power_generation.total_accumulated_energy_kwh, c: e.earth_communication_status.Earth_Visible_Pct, s: e.terrain_topography_physics.Slope_deg })
  const x = g(ea), y = g(eb), r = (v) => Math.round(v * 1e4) / 1e4
  const deltas = { delta_suitability_score: r(y.score - x.score), delta_sunlight_hours: r(y.sun - x.sun), delta_power_watts: r(y.p - x.p), delta_peak_power_watts: r(y.pk - x.pk), delta_energy_kwh: r(y.e - x.e), delta_comms_uptime_pct: r(y.c - x.c), delta_slope_deg: r(y.s - x.s) }
  return { side_by_side_comparison: { convention: 'delta = Scenario B - Scenario A', scenario_a: ea, scenario_b: eb, deltas, higher_score_scenario: deltas.delta_suitability_score > 0 ? 'B' : deltas.delta_suitability_score < 0 ? 'A' : 'tie' } }
}

export function offlineSites({ maxSlope = 15, minSun = 50, minEarth = 40, lat = -90, lon = 0, mode = 'balanced' } = {}) {
  const r = rankSites({ mode, maxSlope, minSun, minEarth }, { lat, lon })
  return { n_sites: r.all.length, priority_mode: mode, sites: r.all, top5_filtered: r.top5, n_sites_passing_filters: r.nPassing, _source: 'offline' }
}

export { MODE_KEYS, terrainScore, clamp }
