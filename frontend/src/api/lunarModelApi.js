// Fetch client for the FastAPI + ML + physics backend, with automatic fallback to the built-in offline engine.
// Validation errors (HTTP 422) are surfaced to the UI; network failures / 5xx silently switch to offline mode.
import { offlineEvaluate, offlineCompare } from './mockSimulationData.js'

// Backend URL: ?api=http://host:port (handy for testing) > VITE_API_URL > http://localhost:8000
export const API_URL = (new URLSearchParams(location.search).get('api') || import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const listeners = new Set()
export const backendStatus = { online: null, health: null, lastError: null }
const notify = () => listeners.forEach((fn) => fn({ ...backendStatus }))
export const onBackendStatus = (fn) => { listeners.add(fn); return () => listeners.delete(fn) }

class OfflineError extends Error {}

async function request(path, { method = 'GET', body, signal, timeoutMs = 20000, blob = false } = {}) {
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(new DOMException('timeout', 'TimeoutError')), timeoutMs)
  const onAbort = () => ctl.abort(signal.reason)
  if (signal) signal.addEventListener('abort', onAbort, { once: true })
  try {
    const res = await fetch(API_URL + path, {
      method, signal: ctl.signal, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined,
    })
    if (res.status === 422) {
      const j = await res.json().catch(() => ({}))
      const msg = Array.isArray(j.detail) ? j.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ') : j.detail || 'invalid input'
      throw Object.assign(new Error(msg), { status: 422 })
    }
    if (!res.ok) throw new OfflineError(`HTTP ${res.status}`)
    if (backendStatus.online !== true) { backendStatus.online = true; backendStatus.lastError = null; notify() }
    return blob ? await res.blob() : await res.json()
  } catch (e) {
    if (e.status === 422) throw e
    if (signal?.aborted && !(e?.name === 'TimeoutError')) throw e // caller cancelled (stale request): not an outage
    if (backendStatus.online !== false) { backendStatus.online = false; backendStatus.lastError = String(e?.message || e); notify() }
    throw new OfflineError(String(e?.message || e))
  } finally {
    clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', onAbort)
  }
}

/** GET /api/health (2.5 s timeout); updates the shared backend status. */
export async function checkHealth() {
  try {
    const h = await request('/api/health', { timeoutMs: 2500 })
    backendStatus.health = h
    notify()
    return h
  } catch {
    backendStatus.health = null
    notify()
    return null
  }
}

async function withFallback(live, offline) {
  try { return { ...(await live()), _source: 'live' } } catch (e) {
    if (e.status === 422) {
      // The backend rejected the input: show the same validation message instead of silently going offline.
      throw e
    }
    if (e?.name === 'AbortError') throw e
    return { ...offline(), _source: 'offline' }
  }
}

/** POST /api/evaluate (full dashboard outputs 1-9 + hourly timeline). */
export const evaluate = (body, signal) =>
  withFallback(() => request('/api/evaluate', { method: 'POST', body, signal }), () => offlineEvaluate(body))

/** POST /api/compare -> { side_by_side_comparison: { scenario_a, scenario_b, deltas } } (timelines included). */
export const compare = (a, b, signal) =>
  withFallback(() => request('/api/compare', { method: 'POST', body: { scenario_a: a, scenario_b: b, include_timeline: true }, signal }), () => offlineCompare(a, b))

/** POST /api/export-csv -> Blob (mission_telemetry_export.csv). Throws when the backend is unreachable. */
export const exportCsvBlob = (body) => request('/api/export-csv', { method: 'POST', body, blob: true, timeoutMs: 30000 })

/** POST /api/warmup (synchronous DEM + demo-site warm-up). */
export const warmup = () => request('/api/warmup', { method: 'POST', timeoutMs: 180000 })

/** Build the API payload from a UI scenario. */
export function buildBody(scn, mode, timelineHourIndex = 0) {
  const body = {
    start_datetime_utc: scn.startISO, duration_hours: scn.durationHours, timeline_hour_index: timelineHourIndex,
    max_slope_deg: scn.maxSlope, min_sun_pct: scn.minSun, min_earth_pct: scn.minEarth,
    tower_height_m: scn.tower, panel_tilt_deg: scn.tilt, panel_area_m2: scn.area, priority_mode: mode,
  }
  if (scn.siteId) body.site_id = scn.siteId
  else { body.lat = scn.lat; body.lon = scn.lon }
  return body
}
