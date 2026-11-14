// Input validation and telemetry checks: invalid coordinates, out-of-bounds parameters and incomplete data are reported as clear
// messages in the interface instead of crashing it. Pure functions (no React), so they are unit-tested in Node (tests/js_edge.mjs).
import { MAX_TOWER_M } from './physics.js'

/** Allowed ranges; keep equal to the backend (api_server.ScenarioIn / mission_simulator.LIMITS). */
export const LIMITS = {
  lat: [-90, -85], lon: [0, 360], tower: [1, MAX_TOWER_M], tilt: [0, 90], area: [1, 50],
  maxSlope: [0, 15], durationDays: [1 / 24, 60], batteryKwh: [1, 2000], loadW: [10, 20000],
}
const UNITS = { lat: '°', lon: '°E', tower: ' m', tilt: '°', area: ' m²', maxSlope: '°', durationDays: ' days', batteryKwh: ' kWh', loadW: ' W' }
const NAMES = { lat: 'Latitude', lon: 'Longitude', tower: 'Tower height', tilt: 'Panel tilt', area: 'Panel area', maxSlope: 'Maximum slope', durationDays: 'Mission duration', batteryKwh: 'Battery capacity', loadW: 'Load' }

/** One range check; returns an issue object or null. Blank, non-numeric, NaN and Infinity are all rejected. */
export function checkRange(field, value) {
  const [lo, hi] = LIMITS[field], u = UNITS[field] || ''
  const n = typeof value === 'string' ? (value.trim() === '' ? NaN : Number(value)) : value
  if (typeof n !== 'number' || !Number.isFinite(n)) return { field, message: `${NAMES[field]} must be a number between ${lo}${u} and ${hi}${u}.`, value }
  if (n < lo || n > hi) return { field, message: `${NAMES[field]} ${n}${u} is outside the allowed range ${lo}${u} to ${hi}${u}.`, value }
  return null
}

/** Issues for a set of fields: validate({lat, lon, tower, ...}) -> [{field, message, value}]. Unknown fields are ignored. */
export const validate = (values) => Object.entries(values).filter(([k]) => k in LIMITS).map(([k, v]) => checkRange(k, v)).filter(Boolean)

/** Validate the current scenario (location, hardware, battery). */
export const validateScenario = (s) => validate({ lat: s.lat, lon: s.lon, tower: s.tower, tilt: s.tilt, area: s.area, maxSlope: s.maxSlope, batteryKwh: s.batteryKwh, loadW: s.loadW })

/** Telemetry fields the dashboard panels read: [path, 'number' | 'string' | 'array' | 'object']. */
export const REQUIRED_TELEMETRY = [
  ['primary_landing_decision.Suitability_Score', 'number'], ['primary_landing_decision.Safety_Class', 'string'],
  ['primary_landing_decision.mission_status_label', 'string'], ['terrain_topography_physics.Slope_deg', 'number'],
  ['terrain_topography_physics.Elevation_m', 'number'], ['solar_illumination_visibility.Sun_Visible_Pct', 'number'],
  ['earth_communication_status.Earth_Visible_Pct', 'number'], ['timeline.sun_el_eff_deg', 'array'], ['timeline.earth_el_eff_deg', 'array'],
  ['timeline.timestamp_utc', 'array'], ['scenario.start_datetime_utc', 'string'], ['xai_and_hazard_alerts', 'object'],
]

const get = (o, path) => path.split('.').reduce((a, k) => (a == null ? undefined : a[k]), o)
const okType = (v, t) => (t === 'number' ? typeof v === 'number' && Number.isFinite(v) : t === 'string' ? typeof v === 'string' && v !== '' : t === 'array' ? Array.isArray(v) && v.length > 0 : v != null && typeof v === 'object')

/** Is the evaluation result complete? -> {ok, missing: [path, ...]} (never throws, even for null / garbage). */
export function checkTelemetry(result) {
  if (result == null || typeof result !== 'object') return { ok: false, missing: REQUIRED_TELEMETRY.map(([p]) => p) }
  const missing = REQUIRED_TELEMETRY.filter(([p, t]) => !okType(get(result, p), t)).map(([p]) => p)
  return { ok: missing.length === 0, missing }
}

/** Turn any error (backend 422 text, network failure, unexpected exception) into a short title + advice for the interface. */
export function describeError(err) {
  const msg = String(err?.message ?? err ?? 'Unknown error')
  if (err?.kind === 'incomplete' || /incomplete telemetry/i.test(msg)) {
    return { kind: 'incomplete', title: 'Telemetry incomplete', detail: 'Some expected data was missing from the response, so this site cannot be analysed.', missing: err?.missing || msg.replace(/^.*missing /i, '').split(', '), advice: 'The previous valid result stays on screen. Try another site or retry; the rest of the dashboard is unaffected.' }
  }
  if (err?.status === 422 || /outside|must be|invalid|unknown site|provide site_id|exceeds|between/i.test(msg)) {
    return { kind: 'input', title: 'Input outside the allowed range', detail: msg, advice: 'Change the highlighted value; nothing was calculated for this input.' }
  }
  if (/HTTP 5\d\d|Failed to fetch|NetworkError|timeout|Load failed|abort/i.test(msg)) {
    return { kind: 'offline', title: 'Backend not reachable', detail: msg, advice: 'Showing the built-in offline estimate (lower confidence). Start the backend to get full-accuracy results.' }
  }
  return { kind: 'unexpected', title: 'Something unexpected happened', detail: msg, advice: 'Reload the page; if it repeats, report the message above.' }
}
