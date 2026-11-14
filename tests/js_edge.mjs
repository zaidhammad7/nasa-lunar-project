// Front-end error handling and physics helpers (frontend/src/lib) evaluated in Node; JSON consumed by tests/test_edge_cases.py.
// Usage: node tests/js_edge.mjs <evaluate-response.json>
import { readFileSync } from 'node:fs'
import { checkRange, validate, validateScenario, checkTelemetry, describeError, REQUIRED_TELEMETRY, LIMITS } from '../frontend/src/lib/validation.js'
import { towerBoostDeg, horizonDistanceKm, MAX_TOWER_M, R_MOON_M } from '../frontend/src/lib/physics.js'

const real = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const out = {}

// boundary values: [value, expected-to-be-accepted]
const probe = (field, cases) => Object.fromEntries(cases.map(([v, ok]) => [String(v), (checkRange(field, v) === null) === ok]))
out.boundaries = {
  tower: probe('tower', [[1, true], [150, true], [0.99, false], [150.01, false], [0, false], [-5, false], ['abc', false], ['', false], [NaN, false], [Infinity, false], [null, false], [undefined, false]]),
  lat: probe('lat', [[-90, true], [-85, true], [-84.999, false], [-90.001, false], [0, false], [NaN, false], ['x', false]]),
  lon: probe('lon', [[0, true], [360, true], [-0.001, false], [360.001, false], [NaN, false]]),
  tilt: probe('tilt', [[0, true], [90, true], [-1, false], [90.1, false]]),
  area: probe('area', [[1, true], [50, true], [0.99, false], [50.1, false]]),
}
out.limitsMatchBackend = { tower: LIMITS.tower[1] === MAX_TOWER_M && MAX_TOWER_M === 150, lat: LIMITS.lat.join() === '-90,-85', lon: LIMITS.lon.join() === '0,360', tilt: LIMITS.tilt.join() === '0,90', area: LIMITS.area.join() === '1,50' }
out.messageNamesFieldAndLimit = /Tower height/.test(checkRange('tower', 151).message) && /150/.test(checkRange('tower', 151).message) && /-85/.test(checkRange('lat', -80).message)
out.validateScenarioClean = validateScenario({ lat: -87, lon: 30, tower: 5, tilt: 80, area: 10, maxSlope: 15, batteryKwh: 50, loadW: 150 }).length === 0
out.validateScenarioFindsAll = validateScenario({ lat: -10, lon: 400, tower: 999, tilt: 99, area: 0, maxSlope: 15, batteryKwh: 50, loadW: 150 }).map((i) => i.field).sort().join()
out.validateIgnoresUnknown = validate({ foo: 1, tower: 5 }).length === 0

// telemetry completeness
out.realOk = checkTelemetry(real).ok
const get = (o, p) => p.split('.').reduce((a, k) => (a == null ? undefined : a[k]), o)
const drop = (o, p) => { const c = structuredClone(o), ks = p.split('.'); let t = c; for (const k of ks.slice(0, -1)) t = t[k]; delete t[ks.at(-1)]; return c }
out.everyMissingFieldDetected = REQUIRED_TELEMETRY.every(([p]) => { const r = checkTelemetry(drop(real, p)); return !r.ok && r.missing.includes(p) })
out.requiredFieldsExistInRealResult = REQUIRED_TELEMETRY.every(([p]) => get(real, p) !== undefined)
const nanResult = structuredClone(real); nanResult.primary_landing_decision.Suitability_Score = NaN
out.nanScoreDetected = !checkTelemetry(nanResult).ok
const emptyTimeline = structuredClone(real); emptyTimeline.timeline.sun_el_eff_deg = []
out.emptyTimelineDetected = !checkTelemetry(emptyTimeline).ok
out.garbageNeverThrows = [null, undefined, 0, 'x', [], {}, 42, true].every((g) => { try { return checkTelemetry(g).ok === false } catch { return false } })

// error descriptions
out.errorKinds = {
  input: describeError(Object.assign(new Error('tower_height_m: tower height must be between 1 and 150 m'), { status: 422 })).kind,
  offline: describeError(new Error('Failed to fetch')).kind,
  offline5xx: describeError(new Error('HTTP 503')).kind,
  unexpected: describeError(new Error('boom')).kind,
  incomplete: describeError(new Error('Incomplete telemetry for This site: missing timeline.sun_el_eff_deg, terrain_topography_physics.Slope_deg')).kind,
  nullErr: describeError(null).kind, undefinedErr: describeError(undefined).kind, stringErr: describeError('x').kind,
}
out.incompleteListsMissing = describeError(new Error('Incomplete telemetry for X: missing a.b, c.d')).missing.join('|') === 'a.b|c.d'
out.errorHasAdvice = ['a', 'Failed to fetch', 'HTTP 500'].every((m) => describeError(new Error(m)).advice.length > 10)

// horizon geometry in the browser
const tangent = (h) => Math.sqrt(2 * R_MOON_M * h + h * h) / 1000
out.horizonDistanceKm = Object.fromEntries([1, 5, 20, 150].map((h) => [h, horizonDistanceKm(h)]))
out.horizonDistanceMatchesTangent = [1, 5, 20, 50, 150].every((h) => Math.abs(horizonDistanceKm(h) - tangent(h)) < 1e-12)
out.dipMatchesIndependent = [1, 5, 20, 50, 150].every((h) => Math.abs(towerBoostDeg(h) - (Math.atan((tangent(h) * 1000) / R_MOON_M) * 180) / Math.PI) < 1e-9)
out.dip = { 20: towerBoostDeg(20), 150: towerBoostDeg(150) }
out.horizonGrowsWithHeight = [1, 5, 20, 50, 150].map(horizonDistanceKm).every((v, i, a) => i === 0 || v > a[i - 1])
console.log(JSON.stringify(out))
