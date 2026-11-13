// Central simulation state: active Site A / Site B scenarios, priority mode, API results (live or offline),
// mission clock (play / pause / speed) and fly-to requests for the 3-D camera.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { evaluate, compare, buildBody, checkHealth, onBackendStatus, backendStatus } from '../api/lunarModelApi.js'
import { siteById, nearestPreset, rankSites } from '../lib/sites.js'
import { timeStore } from '../lib/timeStore.js'
import { BASELINE_START_MS, BASELINE_END_MS, HOUR_MS, iso, modeAdjusted } from '../lib/physics.js'

const START_ISO = iso(BASELINE_START_MS)
export const WINDOW = { startMs: BASELINE_START_MS, endMs: BASELINE_END_MS }

const makeScenario = (id) => {
  const s = siteById(id)
  return { siteId: id, lat: s.lat, lon: s.lon, startISO: START_ISO, durationHours: 1440, maxSlope: 15, minSun: 50, minEarth: 40, tower: 5, tilt: 80, area: 10 }
}

export function useLunarSimulation() {
  const [scn, setScn] = useState({ A: makeScenario('Auto_SP_099'), B: makeScenario('Auto_SP_075') })
  const [editing, setEditing] = useState('A')
  const [compareOn, setCompareOn] = useState(false)
  const [mode, setMode] = useState('balanced')
  const [results, setResults] = useState({ A: null, B: null, deltas: null })
  const [status, setStatus] = useState({ loading: false, error: null })
  const [backend, setBackend] = useState({ ...backendStatus })
  const [fly, setFly] = useState({ id: 0, kind: 'overview' })
  const [activePreset, setActivePreset] = useState(null)
  const [toast, setToast] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeedState] = useState(10)

  // ---------------------------------------------------------------- backend health
  useEffect(() => {
    const off = onBackendStatus((s) => setBackend(s))
    checkHealth()
    const id = setInterval(checkHealth, 6000)
    return () => { off(); clearInterval(id) }
  }, [])

  // ---------------------------------------------------------------- evaluate (debounced, cancellable)
  useEffect(() => {
    const ctl = new AbortController()
    const timer = setTimeout(async () => {
      setStatus((s) => ({ ...s, loading: true }))
      try {
        if (compareOn) {
          const r = await compare(buildBody(scn.A, mode), buildBody(scn.B, mode), ctl.signal)
          const c = r.side_by_side_comparison
          setResults({ A: { ...c.scenario_a, _source: r._source }, B: { ...c.scenario_b, _source: r._source }, deltas: c.deltas })
        } else {
          const r = await evaluate(buildBody(scn.A, mode), ctl.signal)
          setResults({ A: r, B: null, deltas: null })
        }
        setStatus({ loading: false, error: null })
      } catch (e) {
        if (ctl.signal.aborted) return
        setStatus({ loading: false, error: e.message })
      }
    }, 260)
    return () => { clearTimeout(timer); ctl.abort() }
  }, [scn, mode, compareOn])

  const editKey = compareOn ? editing : 'A'
  const active = results[editKey] || results.A
  const activeScn = scn[editKey]

  // mission clock follows the active scenario's window
  useEffect(() => {
    const r = active
    if (!r) return
    const startIdx = Math.round((Date.parse(r.scenario.start_datetime_utc) - BASELINE_START_MS) / HOUR_MS)
    timeStore.configure(r.scenario.duration_hours, startIdx)
  }, [active])

  // ---------------------------------------------------------------- play / pause driver
  useEffect(() => { timeStore.playing = playing; timeStore.speed = speed }, [playing, speed])
  useEffect(() => {
    let raf, last = performance.now()
    const loop = (now) => {
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      if (timeStore.playing) {
        let h = timeStore.hours + dt * timeStore.speed
        if (h >= timeStore.length - 1) h = 0
        timeStore.set(h)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  // ---------------------------------------------------------------- actions
  const showToast = useCallback((msg) => { setToast(msg); setTimeout(() => setToast((t) => (t === msg ? null : t)), 3500) }, [])
  const requestFly = useCallback((kind, lat, lon) => { setFly((f) => ({ id: f.id + 1, kind, lat, lon })); setActivePreset(kind) }, [])

  const patch = useCallback((p) => setScn((prev) => ({ ...prev, [editKey]: { ...prev[editKey], ...p } })), [editKey])

  const selectSite = useCallback((id) => {
    const s = siteById(id)
    if (!s) return
    patch({ siteId: id, lat: s.lat, lon: s.lon })
    requestFly('site', s.lat, s.lon)
  }, [patch, requestFly])

  /** Manual coordinates (typed or picked on the 3-D Moon). Snaps to a preset within 50 m. */
  const setLatLon = useCallback((lat, lon, { fromPick = false } = {}) => {
    if (!(lat >= -90 && lat <= -85)) { if (fromPick) showToast(`Latitude ${lat.toFixed(2)}° is outside the −85°…−90° study cap`); return false }
    const lonN = ((lon % 360) + 360) % 360
    const preset = nearestPreset(lat, lonN)
    patch(preset ? { siteId: preset.id, lat: preset.lat, lon: preset.lon } : { siteId: null, lat, lon: lonN })
    requestFly('site', lat, lonN)
    return true
  }, [patch, requestFly, showToast])

  const jumpToWindow = useCallback((w) => {
    patch({ startISO: w.start_utc, durationHours: w.duration_hours })
    timeStore.set(0)
  }, [patch])

  const toggleCompare = useCallback(() => { setCompareOn((v) => !v); setEditing('A') }, [])
  const setSpeed = useCallback((s) => setSpeedState(s), [])

  // ---------------------------------------------------------------- derived: ranked sites (instant, mirrors the backend)
  const filters = { maxSlope: activeScn.maxSlope, minSun: activeScn.minSun, minEarth: activeScn.minEarth }
  const ranking = useMemo(
    () => rankSites({ mode, ...filters }, { lat: activeScn.lat, lon: activeScn.lon }, activeScn.siteId),
    [mode, filters.maxSlope, filters.minSun, filters.minEarth, activeScn.lat, activeScn.lon, activeScn.siteId], // eslint-disable-line react-hooks/exhaustive-deps
  )

  /** Score shown right now: instantly re-weighted for the selected mode while the backend refresh is in flight. */
  const liveScore = useMemo(() => (active ? modeAdjusted(active, mode) : null), [active, mode])

  return {
    scn, editing: editKey, setEditing, compareOn, toggleCompare, mode, setMode,
    results, active, activeScn, status, backend, patch, selectSite, setLatLon, jumpToWindow,
    fly, requestFly, activePreset, toast, showToast, ranking, liveScore,
    playing, setPlaying, speed, setSpeed,
  }
}
