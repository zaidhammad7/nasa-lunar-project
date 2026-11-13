// Browser-side (frontend/src/lib) computations, evaluated in Node and printed as JSON for tests/test_all.py,
// which compares them with the Python backend.  Usage: node tests/js_checks.mjs <sitesData.json>
import { readFileSync } from 'node:fs'
import * as P from '../frontend/src/lib/physics.js'
import { simulateBattery, requiredCapacityKwh, longestDarkHours } from '../frontend/src/lib/survival.js'
import { rampColor, HEAT_RANGE } from '../frontend/src/lib/heatmap.js'
import { LANDMARKS } from '../frontend/src/lib/landmarks.js'

const sites = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const out = {}

out.towerBoost = [1, 20, 150].map(P.towerBoostDeg)
out.discFraction = [-1, -0.265, 0, 0.265, 1].map(P.sunDiscFraction)
out.illumination = [-1, 0, 1].map(P.illuminationState)
out.power = [[5, 10, 85], [1, 20, 45], [-0.1, 10, 90], [0.2, 5, 80], [6.5, 50, 0]].map(([el, a, t]) => P.powerWatts(el, a, t))
out.effectiveMaxSlope = P.effectiveMaxSlope(15)
out.constants = { MAX_TOWER_M: P.MAX_TOWER_M, SLOPE_MARGIN_DEG: P.SLOPE_MARGIN_DEG, ROUGHNESS_WEIGHT: P.ROUGHNESS_WEIGHT,
  SCORE_BUFFER: P.SCORE_BUFFER, ACCEPTABLE_MIN: P.ACCEPTABLE_MIN, SAFETY_CAP: P.SAFETY_CAP, R_MOON_M: P.R_MOON_M }
out.modeWeights = Object.fromEntries(P.MODE_KEYS.map((m) => [m, P.MODES[m].w]))
out.components = Object.fromEntries(sites.map((s) => [s.id, P.components(s.slope, s.sun, s.sunMax, s.earth, s.earthAvg)]))
out.modeScores = Object.fromEntries(P.MODE_KEYS.map((m) => [m, Object.fromEntries(sites.map((s) =>
  [s.id, P.compositeScore(P.components(s.slope, s.sun, s.sunMax, s.earth, s.earthAvg), m)]))]))
out.haversine = [[-90, 0, -85, 0], [-85.3109, 332.293, -85.4735, 29.2177], [-88, 10, -88, 190]].map((a) => P.haversineKm(...a))

// lat/lon <-> scene vector round trip (deterministic pseudo-random points over the cap)
let worst = 0, seed = 7
const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 }
for (let i = 0; i < 2000; i++) {
  const lat = -85 - 5 * rnd(), lon = 360 * rnd()
  const b = P.vecToLatLon(...P.latLonToVec(lat, lon))
  const dLon = Math.min(Math.abs(b.lon - lon), 360 - Math.abs(b.lon - lon))
  worst = Math.max(worst, Math.abs(b.lat - lat), lat < -89.999 ? 0 : dLon)
}
out.roundTripMaxErrDeg = worst

const synth = [...Array(100).fill(0), ...Array(50).fill(1000)]
out.battery = simulateBattery(synth, 10, 150)
out.requiredKwh = requiredCapacityKwh(synth, 150)
out.longestDark = longestDarkHours(synth)
out.ramp = { low: rampColor(HEAT_RANGE[0] - 10), mid: rampColor((HEAT_RANGE[0] + HEAT_RANGE[1]) / 2), high: rampColor(HEAT_RANGE[1] + 10) }
out.landmarks = LANDMARKS

console.log(JSON.stringify(out))
