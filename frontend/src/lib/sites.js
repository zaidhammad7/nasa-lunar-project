// The 100 candidate sites (final_lunar_dataset_fixed.csv + LOLA roughness) and the client-side re-ranking that
// mirrors the backend (mission_simulator.passes_filters / mode_scores / display_class).
import RAW from '../api/sitesData.json'
import {
  components, compositeScore, effectiveMaxSlope, ROUGHNESS_WEIGHT, haversineKm, bearingDeg, SLOPE_MARGIN_DEG,
} from './physics.js'

export const SITES = RAW.map((s) => ({ ...s, comp: components(s.slope, s.sun, s.sunMax, s.earth, s.earthAvg) }))
export const SITE_BY_ID = Object.fromEntries(SITES.map((s) => [s.id, s]))
export const siteById = (id) => SITE_BY_ID[id] || null

/** Rule class with the 13.5 deg safety-factor derating applied (colour of the 3-D markers). */
export const displayClass = (s) =>
  s.slope > effectiveMaxSlope(15) || s.slope + ROUGHNESS_WEIGHT * s.rough > 15 ? 'Hazardous' : s.ruleClass

export const passesFilters = (s, { maxSlope, minSun, minEarth }) =>
  s.slope <= effectiveMaxSlope(maxSlope) && s.slope + ROUGHNESS_WEIGHT * s.rough <= maxSlope && s.sun >= minSun && s.earth >= minEarth

export function nearestPreset(lat, lon, maxKm = 0.05) {
  let best = null, bd = Infinity
  for (const s of SITES) { const d = haversineKm(lat, lon, s.lat, s.lon); if (d < bd) { bd = d; best = s } }
  return bd <= maxKm ? best : null
}

/** All sites with mode score / rank / filter flag / distance + bearing from `ref`, plus the filtered top 5. */
export function rankSites({ mode, maxSlope, minSun, minEarth }, ref, excludeId = null) {
  const scored = SITES.map((s) => ({ ...s, modeScore: compositeScore(s.comp, mode) }))
  const byScore = [...scored].sort((a, b) => b.modeScore - a.modeScore)
  byScore.forEach((s, i) => { s.rankInMode = i + 1 })
  const out = byScore.map((s) => ({
    ...s,
    displayClass: displayClass(s),
    passes: passesFilters(s, { maxSlope, minSun, minEarth }),
    distanceKm: ref ? haversineKm(ref.lat, ref.lon, s.lat, s.lon) : null,
    bearing: ref ? bearingDeg(ref.lat, ref.lon, s.lat, s.lon) : null,
  }))
  const top5 = out.filter((s) => s.passes && s.id !== excludeId).slice(0, 5)
  return { all: out, top5, nPassing: out.filter((s) => s.passes).length, effectiveMaxSlope: effectiveMaxSlope(maxSlope), margin: SLOPE_MARGIN_DEG }
}

/** Mean of the 4 nearest dataset sites (polar-plane distance), inverse-distance weighted. */
export function idw(lat, lon, key) {
  const p = (la, lo) => [(90 + la) * Math.cos((lo * Math.PI) / 180), (90 + la) * Math.sin((lo * Math.PI) / 180)]
  const [x, y] = p(lat, lon)
  const near = SITES.map((s) => { const [sx, sy] = p(s.lat, s.lon); return { s, d: Math.hypot(sx - x, sy - y) } }).sort((a, b) => a.d - b.d).slice(0, 4)
  const w = near.map((n) => 1 / Math.max(n.d, 1e-6))
  return near.reduce((acc, n, i) => acc + n.s[key] * w[i], 0) / w.reduce((a, b) => a + b, 0)
}
