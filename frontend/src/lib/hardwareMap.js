// Safe-zone map for the user's own hardware: every one of the 100 sites re-evaluated with the current tower height,
// panels and battery. Mirrors the backend rules (guardrails, 3-layer safety factor, fixed 5.0 deg Optimal slope rule) with the
// same rule-based stand-in the offline engine uses, then adds the power-survival gate (battery through the longest night).
import {
  analyticSeries, calibrate, towerBoostDeg, powerWatts, components, compositeScore, effectiveMaxSlope, ROUGHNESS_WEIGHT,
  SCORE_BUFFER, ACCEPTABLE_MIN, SAFETY_CAP, OPTIMAL_MAX_SLOPE_DEG, CI_HALF, BASELINE_START_MS, HOUR_MS, N_SAMPLES, clamp,
} from './physics.js'
import { simulateBattery } from './survival.js'

const MIN_SUN_PCT = 25, MIN_EARTH_PCT = 10 // hard guardrails (predict_site.GUARDRAILS)
const base = new Map() // site id -> mast-free calibrated Sun / Earth elevation series (deg), computed once

function baseSeries(s) {
  let b = base.get(s.id)
  if (!b) {
    const a = analyticSeries(s.lat, s.lon)
    b = { sun: calibrate(a.sun, s.sun, s.sunAvg, s.sunMax), earth: calibrate(a.earth, s.earth, s.earthAvg, s.earthMax) }
    base.set(s.id, b)
  }
  return b
}

/**
 * Evaluate one site for a hardware set.
 * @param hw {tower (m), tilt (deg), area (m2), batteryKwh, loadW, startISO, durationHours, mode, maxSlope}
 * @returns {displayClass, modeScore, sunPct, earthPct, survives, minSocPct, reason}
 */
export function evaluateSiteForHardware(s, hw) {
  const { sun, earth } = baseSeries(s)
  const boost = towerBoostDeg(hw.tower)
  const startIdx = clamp(Math.round((Date.parse(hw.startISO) - BASELINE_START_MS) / HOUR_MS), 0, N_SAMPLES - 2)
  const L = Math.max(1, Math.min(Math.round(hw.durationHours), N_SAMPLES - startIdx))
  let lit = 0, dte = 0, sunMax = -Infinity, earthMax = -Infinity, earthSum = 0
  const P = new Float64Array(L)
  for (let i = 0; i < L; i++) {
    const se = sun[startIdx + i] + boost, ee = earth[startIdx + i] + boost
    if (se > 0) lit++
    if (ee > 0) dte++
    if (se > sunMax) sunMax = se
    if (ee > earthMax) earthMax = ee
    earthSum += ee
    P[i] = powerWatts(se, hw.area, hw.tilt)
  }
  const sunPct = (lit / L) * 100, earthPct = (dte / L) * 100
  const comp = components(s.slope, sunPct, sunMax, earthPct, earthSum / L)
  const ruleBal = compositeScore(comp, 'balanced')
  const maxSlope = hw.maxSlope ?? 15

  // verdict rules (same order of strictness as the backend)
  const hazard = s.slope > 15 || sunPct < MIN_SUN_PCT || earthPct < MIN_EARTH_PCT
    || s.slope > effectiveMaxSlope(maxSlope) || s.slope + ROUGHNESS_WEIGHT * (s.rough || 0) > maxSlope
    || ruleBal < ACCEPTABLE_MIN + SCORE_BUFFER || ruleBal - CI_HALF < ACCEPTABLE_MIN
  let cls = hazard ? 'Hazardous' : s.slope <= OPTIMAL_MAX_SLOPE_DEG && ruleBal >= 65 ? 'Optimal' : 'Acceptable'
  let reason = hazard ? 'terrain / sunlight / comms' : null

  const bat = simulateBattery(P, hw.batteryKwh, hw.loadW)
  if (cls !== 'Hazardous' && !bat.survives) { cls = 'Hazardous'; reason = 'battery depleted' }

  const raw = compositeScore(comp, hw.mode || 'balanced')
  return { displayClass: cls, modeScore: cls === 'Hazardous' ? Math.min(raw, SAFETY_CAP) : raw, sunPct, earthPct, survives: bat.survives, minSocPct: bat.minSocPct, reason }
}

/** {siteId: evaluation} for a list of sites (the 100 scored sites). */
export function evaluateAllSites(sites, hw) {
  return Object.fromEntries(sites.map((s) => [s.id, evaluateSiteForHardware(s, hw)]))
}

export const countClasses = (evals) => Object.values(evals).reduce((a, e) => { a[e.displayClass] = (a[e.displayClass] || 0) + 1; return a }, { Optimal: 0, Acceptable: 0, Hazardous: 0 })
