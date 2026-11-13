// Shared lunar physics (JS port of the backend's mission_simulator / ephemeris_series / suitability).
// Used for 60 FPS local recomputation (power, illumination, countdowns, mode re-scoring, ranking) and by
// the offline fallback engine. Units: degrees, metres, hours (UTC), watts.

export const R_MOON_M = 1_737_400
export const R_MOON_KM = 1737.4
export const SUN_ANG_RADIUS = 0.265
export const S0 = 1361.0
export const ETA_PV = 0.3
export const N_SAMPLES = 1441
export const BASELINE_START_MS = Date.UTC(2026, 10, 13, 0, 0, 0)
export const BASELINE_END_MS = BASELINE_START_MS + 1440 * 3600_000
export const HOUR_MS = 3600_000

export const P_SYN = 29.530589 * 24 // 708.73 h: Sun's sweep around the sky
export const P_DRAC = 27.212221 * 24 // 653.09 h: latitude libration of the sub-Earth point
export const P_ANOM = 27.55455 * 24 // 661.31 h: longitude libration of the sub-Earth point
// Least-squares fit to real JPL Horizons series (same constants as src/analysis/ephemeris_series.py)
export const MODEL = {
  sun: { lam0: 139.64631912569732, d0: -1.3096994682591019, d1: 0.38634871211499355 },
  earth: { bAmp: 6.556147658458688, bPhase: 2.216299918376506, lAmp: 12.0, lPhase: 3.285194062826637 },
}

export const MODES = {
  most_safety: { label: 'MOST SAFETY', short: 'Safety', w: [0.6, 0.25, 0.15], hint: 'Terrain-first: flattest slopes' },
  balanced: { label: 'BALANCED', short: 'Balanced', w: [0.4, 0.35, 0.25], hint: 'Standard Artemis weighting' },
  most_power: { label: 'MOST POWER', short: 'Power', w: [0.2, 0.6, 0.2], hint: 'Energy-first: peaks of eternal light' },
}
export const MODE_KEYS = ['most_safety', 'balanced', 'most_power']
export const SLOPE_MARGIN_DEG = 1.5
export const ROUGHNESS_WEIGHT = 0.5
export const SCORE_BUFFER = 3.0
export const ACCEPTABLE_MIN = 45.0
export const SAFETY_CAP = 44.0
export const DEFAULT_MIN_SUN = 25 // % of time; keep equal to predict_site.DEFAULT_MIN_SUN_PCT (real, terrain-shadowed sunlight)
export const DEFAULT_MIN_EARTH = 20 // keep equal to predict_site.DEFAULT_MIN_EARTH_PCT

const RAD = Math.PI / 180
const DEG = 180 / Math.PI
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

// ---------------------------------------------------------------- hardware / illumination / power
export const mastDrawHeight = (h) => 0.035 + Math.min(h, 20) * 0.0045 + Math.max(0, h - 20) * 0.0006 // scene units; exaggerated, compressed above 20 m
export const MAX_TOWER_M = 150 // keep equal to predict_site.MAX_TOWER_HEIGHT_M
export const towerBoostDeg = (h) => Math.acos(R_MOON_M / (R_MOON_M + h)) * DEG
export const sunDiscFraction = (el) => clamp((el + SUN_ANG_RADIUS) / (2 * SUN_ANG_RADIUS), 0, 1)
export const illuminationState = (el) => (el >= SUN_ANG_RADIUS ? 'Direct Sunlight' : el <= -SUN_ANG_RADIUS ? 'Total Darkness' : 'Partial Shadow')
export const stateCode = (el) => (el >= SUN_ANG_RADIUS ? 2 : el <= -SUN_ANG_RADIUS ? 0 : 1)
export const STATE_NAMES = ['Total Darkness', 'Partial Shadow', 'Direct Sunlight']
export const powerWatts = (el, area, tilt) =>
  S0 * ETA_PV * area * sunDiscFraction(el) * Math.max(0, Math.sin((el + tilt) * RAD))
export const DTE_CONNECTED = 'Connected (Line-of-Sight Clear)'
export const DTE_BLOCKED = 'Blocked (Signal Lost)'

// ---------------------------------------------------------------- scoring (mirror of suitability.py)
export const terrainScore = (slope, ideal = 5, limit = 15) => {
  const s = Math.abs(slope)
  const v = s <= ideal ? 100 : s <= limit ? 100 - (50 * (s - ideal)) / (limit - ideal) : 50 - 5 * (s - limit)
  return clamp(v, 0, 100)
}
export const solarScore = (visPct, maxEl) => 0.7 * clamp(visPct, 0, 100) + 0.3 * clamp(maxEl / 7, 0, 1) * 100
export const commsScore = (visPct, avgEl) => 0.7 * clamp(visPct, 0, 100) + 0.3 * clamp((avgEl + 6) / 10, 0, 1) * 100
export const components = (slope, sunPct, sunMax, earthPct, earthAvg) => ({
  terrain: terrainScore(slope), solar: solarScore(sunPct, sunMax), comms: commsScore(earthPct, earthAvg),
})
export const compositeScore = (c, mode) => {
  const [wt, ws, wc] = MODES[mode].w
  return wt * c.terrain + ws * c.solar + wc * c.comms
}
export const effectiveMaxSlope = (maxSlope) => Math.max(0, maxSlope - SLOPE_MARGIN_DEG)

/** Score under another priority mode, from a backend result (ML score shifted by the composite change). */
export function modeAdjusted(result, mode) {
  const p = result?.primary_landing_decision
  const comp = result?.xai_and_hazard_alerts?.component_scores
  if (!p || !comp || p.Suitability_Score_raw_ml == null) return p?.Suitability_Score ?? null
  const base = clamp(p.Suitability_Score_raw_ml + (compositeScore(comp, mode) - compositeScore(comp, 'balanced')), 0, 100)
  const hazardous = p.Safety_Class === 'Hazardous'
  const hard = p.guardrails?.score_cap
  const cap = hazardous ? Math.min(hard ?? Infinity, SAFETY_CAP) : hard ?? Infinity
  return Math.round(Math.min(base, cap) * 100) / 100
}

// ---------------------------------------------------------------- geometry
export const haversineKm = (lat1, lon1, lat2, lon2) => {
  const p1 = lat1 * RAD, p2 = lat2 * RAD, dl = (lon2 - lon1) * RAD
  const a = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2
  return 2 * R_MOON_KM * Math.asin(Math.sqrt(clamp(a, 0, 1)))
}
export const bearingDeg = (lat1, lon1, lat2, lon2) => {
  const p1 = lat1 * RAD, p2 = lat2 * RAD, dl = (lon2 - lon1) * RAD
  const y = Math.sin(dl) * Math.cos(p2)
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)
  return (Math.atan2(y, x) * DEG + 360) % 360
}
export const compass = (b) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.floor(((b + 22.5) % 360) / 45)]

/**
 * Selenographic (lat, lon east) -> vector in the scene frame: +Y = lunar north (-Y = south pole), lon 0 at +X and east
 * toward -Z. This is exactly how three.js wraps an equirectangular map on a SphereGeometry (image centre = +X, east to the
 * right), so real lunar textures land on the right coordinates and longitudes are not mirrored.
 */
export const latLonToVec = (lat, lon, r = 1) => {
  const la = lat * RAD, lo = lon * RAD
  return [r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), -r * Math.cos(la) * Math.sin(lo)]
}
/** Inverse of latLonToVec for any point on / above the surface (lon in [0, 360)). */
export const vecToLatLon = (x, y, z) => {
  // atan2 keeps full precision near the poles, where asin(y / r) loses digits (its slope is infinite at |y / r| = 1)
  return { lat: Math.atan2(y, Math.hypot(x, z)) * DEG, lon: ((Math.atan2(-z, x) * DEG) % 360 + 360) % 360 }
}

// ---------------------------------------------------------------- analytic ephemeris (flat-horizon model)
export const subSolarPoint = (t) => {
  const m = MODEL.sun
  return { lat: m.d0 + (m.d1 * (t - 720)) / 720, lon: (((m.lam0 - (360 * t) / P_SYN) % 360) + 360) % 360 }
}
export const subEarthPoint = (t) => {
  const m = MODEL.earth
  return {
    lat: m.bAmp * Math.sin((2 * Math.PI * t) / P_DRAC + m.bPhase),
    lon: m.lAmp * Math.sin((2 * Math.PI * t) / P_ANOM + m.lPhase),
  }
}
/** Sun / Earth unit directions in the Moon-fixed scene frame at `t` hours after 2026-11-13T00:00Z. */
export const sunDirection = (t) => { const p = subSolarPoint(t); return latLonToVec(p.lat, p.lon) }
export const earthDirection = (t) => { const p = subEarthPoint(t); return latLonToVec(p.lat, p.lon) }

export function sunElevation(lat, lon, t) {
  const m = MODEL.sun, phi = lat * RAD
  const d = (m.d0 + (m.d1 * (t - 720)) / 720) * RAD
  const lamSS = m.lam0 - (360 * t) / P_SYN
  const s = Math.sin(phi) * Math.sin(d) + Math.cos(phi) * Math.cos(d) * Math.cos((lon - lamSS) * RAD)
  return Math.asin(clamp(s, -1, 1)) * DEG
}
export function earthElevation(lat, lon, t) {
  const m = MODEL.earth, phi = lat * RAD
  const b = m.bAmp * Math.sin((2 * Math.PI * t) / P_DRAC + m.bPhase) * RAD
  const l = m.lAmp * Math.sin((2 * Math.PI * t) / P_ANOM + m.lPhase)
  const s = Math.sin(phi) * Math.sin(b) + Math.cos(phi) * Math.cos(b) * Math.cos((lon - l) * RAD)
  const g = Math.asin(clamp(s, -1, 1))
  return (g - (R_MOON_KM / 384400) * Math.cos(g)) * DEG
}
export function analyticSeries(lat, lon) {
  const sun = new Float64Array(N_SAMPLES), earth = new Float64Array(N_SAMPLES)
  for (let i = 0; i < N_SAMPLES; i++) { sun[i] = sunElevation(lat, lon, i); earth[i] = earthElevation(lat, lon, i) }
  return { sun, earth }
}

export const PERMANENT_MARGIN_DEG = 1.6 // keep equal to terrain_illumination.PERMANENT_MARGIN_DEG
/** Effective terrain horizon (deg): the fraction of samples with el > h equals visPct (mirrors terrain_illumination.horizon_for). */
export function horizonFor(el, visPct) {
  const p = clamp(visPct, 0, 100) / 100
  let mx = -Infinity, mn = Infinity
  for (const v of el) { if (v > mx) mx = v; if (v < mn) mn = v }
  if (p <= 0) return mx + PERMANENT_MARGIN_DEG // never lit in NASA's 4-year record: stays dark in every season, with any mast
  if (p >= 1) return Math.min(mn - PERMANENT_MARGIN_DEG, 0)
  const s = Float64Array.from(el).sort(), q = (1 - p) * (s.length - 1), i = Math.floor(q)
  return s[i] + (s[Math.min(i + 1, s.length - 1)] - s[i]) * (q - i) // linear-interpolated quantile, as numpy
}

// ---------------------------------------------------------------- calibration to a site's dataset statistics
function solve3(M, b) {
  const det = (m) => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
  const D = det(M)
  if (Math.abs(D) < 1e-12) return null
  return [0, 1, 2].map((c) => det(M.map((row, r) => row.map((v, k) => (k === c ? b[r] : v)))) / D)
}
/** Monotone remap so max, mean and visible fraction equal the dataset's (same algorithm as the backend). */
export function calibrate(el, visPct, avg, max) {
  const n = el.length
  let smax = -Infinity, smin = Infinity, mean = 0, mean2 = 0
  for (const v of el) { if (v > smax) smax = v; if (v < smin) smin = v; mean += v; mean2 += v * v }
  mean /= n; mean2 /= n
  const sorted = Float64Array.from(el).sort()
  const nVis = Math.round((visPct / 100) * n)
  let sStar = 0, A = null, rhs = null
  if (nVis > 0 && nVis < n) {
    const k = n - nVis
    sStar = 0.5 * (sorted[k - 1] + sorted[k])
    A = [[1, smax, smax ** 2], [1, mean, mean2], [1, sStar, sStar ** 2]]; rhs = [max, avg, 0]
  } else if (nVis >= n) {
    A = [[1, smax, smax ** 2], [1, mean, mean2], [1, smin, smin ** 2]]; rhs = [max, avg, Math.max(0.05, 2 * avg - max)]
  }
  if (A) {
    const a = solve3(A, rhs)
    if (a) {
      let mono = true
      for (let i = 0; i <= 200; i++) { const g = smin + ((smax - smin) * i) / 200; if (!(a[1] + 2 * a[2] * g > 0)) { mono = false; break } }
      if (mono) return el.map((s) => a[0] + a[1] * s + a[2] * s * s)
    }
  }
  if (nVis > 0 && nVis < n) {
    let ap = 0, bn = 0
    for (const v of el) { const d = v - sStar; if (d >= 0) ap += d; else bn += d }
    ap /= n; bn /= n
    const mHi = max / Math.max(smax - sStar, 1e-9)
    const mLo = bn < 0 ? (avg - mHi * ap) / bn : 0
    if (mLo > 0) return el.map((v) => { const d = v - sStar; return d >= 0 ? mHi * d : mLo * d })
  }
  const scale = (max - avg) / Math.max(smax - mean, 1e-9)
  return el.map((v) => avg + scale * (v - mean))
}

// ---------------------------------------------------------------- horizon crossings / countdowns
export function crossingTimes(el, dir) {
  const out = []
  for (let i = 0; i < el.length - 1; i++) {
    const a = el[i], b = el[i + 1]
    if (dir === 'down' ? a > 0 && b <= 0 : a <= 0 && b > 0) out.push(i + a / (a - b))
  }
  return out
}
/** Time from sample `idx` to the next set (if above the horizon) or rise (if below). Same shape as the backend. */
export function nextEvent(el, idx, startMs = BASELINE_START_MS) {
  const lit = el[idx] > 0
  const ct = crossingTimes(el, lit ? 'down' : 'up')
  const k = ct.findIndex((c) => c >= idx)
  const out = { currently_above_horizon: lit, event: lit ? 'set' : 'rise' }
  if (k < 0) return { ...out, hours: null, days: null, hours_component: null, minutes: null, formatted: null, event_time_utc: null, note: `no ${out.event} before the end of the ephemeris window` }
  const hrs = ct[k] - idx
  const totalMin = Math.round(hrs * 60)
  const d = Math.floor(totalMin / 1440), h = Math.floor((totalMin % 1440) / 60), m = totalMin % 60
  return { ...out, hours: hrs, days: d, hours_component: h, minutes: m, formatted: `${d}d ${h}h ${m}m`,
    event_time_utc: new Date(startMs + ct[k] * HOUR_MS).toISOString().replace('.000Z', 'Z'), note: null }
}

export const iso = (ms) => new Date(ms).toISOString().replace('.000Z', 'Z')
