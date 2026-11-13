// Central simulation state: the selected scenario (Site A), an optional comparison location (Site B), the priority mode,
// API results (live, with an instant offline estimate while a custom point is being evaluated), the mission clock and
// fly-to requests for the 3-D camera.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { evaluate, compare, buildBody, checkHealth, onBackendStatus, backendStatus } from '../api/lunarModelApi.js'
import { offlineEvaluate } from '../api/mockSimulationData.js'
import { siteById, rankSites } from '../lib/sites.js'
import { timeStore } from '../lib/timeStore.js'
import { BASELINE_START_MS, HOUR_MS, iso, modeAdjusted, DEFAULT_MIN_SUN, DEFAULT_MIN_EARTH } from '../lib/physics.js'

const START_ISO = iso(BASELINE_START_MS)

const makeScenario = (id) => {
  const s = siteById(id)
  return { siteId: id, lat: s.lat, lon: s.lon, startISO: START_ISO, durationHours: 1440, maxSlope: 15, minSun: DEFAULT_MIN_SUN, minEarth: DEFAULT_MIN_EARTH, tower: 5, tilt: 80, area: 10 }
}

function useStored(key, initial) {
  const [v, setV] = useState(() => { try { const s = localStorage.getItem(key); return s == null ? initial : JSON.parse(s) } catch { return initial } })
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* private mode */ } }, [key, v])
  return [v, setV]
}

export function useLunarSimulation() {
  const [scn, setScn] = useState(() => makeScenario('Auto_SP_099'))
  const [bLoc, setBLoc] = useState(() => { const s = siteById('Auto_SP_075'); return { siteId: s.id, lat: s.lat, lon: s.lon } })
  const [compareOpen, setCompareOpen] = useState(false)
  const [mode, setMode] = useState('balanced')
  const [showPresets, setShowPresets] = useStored('lunar.showPresets', true)
  const [panels, setPanels] = useStored('lunar.panels', { left: true, right: true, header: true })
  const [results, setResults] = useState({ A: null, B: null, deltas: null })
  const [status, setStatus] = useState({ loading: false, error: null })
  const [backend, setBackend] = useState({ ...backendStatus })
  const [fly, setFly] = useState({ id: 0, kind: 'overview' })
  const [activePreset, setActivePreset] = useState(null)
  const [toast, setToast] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeedState] = useState(10)

  const scnB = useMemo(() => ({ ...scn, ...bLoc }), [scn, bLoc]) // Site B shares Site A's date and hardware

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
    const bodyA = buildBody(scn, mode)
    // A custom point can take a few seconds on the backend (Horizons budget / DEM read): show an instant offline estimate
    // right away and replace it with the authoritative backend result when it arrives.
    if (!scn.siteId) {
      try { setResults((r) => ({ ...r, A: { ...offlineEvaluate(bodyA), _source: 'offline', _pending: true } })) } catch { /* invalid input is reported by the real call */ }
    }
    const timer = setTimeout(async () => {
      setStatus((s) => ({ ...s, loading: true }))
      try {
        if (compareOpen) {
          const r = await compare(bodyA, buildBody(scnB, mode), ctl.signal)
          const c = r.side_by_side_comparison
          setResults({ A: { ...c.scenario_a, _source: r._source }, B: { ...c.scenario_b, _source: r._source }, deltas: c.deltas })
        } else {
          const r = await evaluate(bodyA, ctl.signal)
          setResults({ A: r, B: null, deltas: null })
        }
        setStatus({ loading: false, error: null })
      } catch (e) {
        if (ctl.signal.aborted) return
        setStatus({ loading: false, error: e.message })
      }
    }, 200)
    return () => { clearTimeout(timer); ctl.abort() }
  }, [scn, scnB, mode, compareOpen])

  const active = results.A

  // mission clock follows the active scenario's window
  useEffect(() => {
    if (!active) return
    const startIdx = Math.round((Date.parse(active.scenario.start_datetime_utc) - BASELINE_START_MS) / HOUR_MS)
    timeStore.configure(active.scenario.duration_hours, startIdx)
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
  const patch = useCallback((p) => setScn((prev) => ({ ...prev, ...p })), [])

  const selectSite = useCallback((id) => {
    const s = siteById(id)
    if (!s) return
    patch({ siteId: id, lat: s.lat, lon: s.lon })
    requestFly('site', s.lat, s.lon)
  }, [patch, requestFly])

  /** Any coordinate inside the study cap (typed or clicked on the Moon). Never snapped to a preset. */
  const setLatLon = useCallback((lat, lon, { fromPick = false } = {}) => {
    if (!(lat >= -90 && lat <= -85) || !Number.isFinite(lon)) { showToast(`Latitude ${Number(lat).toFixed(2)}° is outside the −85°…−90° study cap`); return false }
    const lonN = ((lon % 360) + 360) % 360
    patch({ siteId: null, lat, lon: lonN })
    requestFly('site', lat, lonN)
    if (fromPick) showToast(`Selected ${lat.toFixed(4)}°, ${lonN.toFixed(4)}°E`)
    return true
  }, [patch, requestFly, showToast])

  const selectSiteB = useCallback((id) => { const s = siteById(id); if (s) setBLoc({ siteId: id, lat: s.lat, lon: s.lon }) }, [])
  const setLatLonB = useCallback((lat, lon) => {
    if (!(lat >= -90 && lat <= -85) || !Number.isFinite(lon)) { showToast('Site B latitude must be within −85°…−90°'); return }
    setBLoc({ siteId: null, lat, lon: ((lon % 360) + 360) % 360 })
  }, [showToast])

  const jumpToWindow = useCallback((w) => { patch({ startISO: w.start_utc, durationHours: w.duration_hours }); timeStore.set(0) }, [patch])
  const togglePanel = useCallback((k) => setPanels((p) => ({ ...p, [k]: !p[k] })), [setPanels])

  // ---------------------------------------------------------------- derived: ranked sites (instant, mirrors the backend)
  const ranking = useMemo(
    () => rankSites({ mode, maxSlope: scn.maxSlope, minSun: scn.minSun, minEarth: scn.minEarth }, { lat: scn.lat, lon: scn.lon }, scn.siteId),
    [mode, scn.maxSlope, scn.minSun, scn.minEarth, scn.lat, scn.lon, scn.siteId],
  )
  /** Score shown right now: instantly re-weighted for the selected mode while the backend refresh is in flight. */
  const liveScore = useMemo(() => (active ? modeAdjusted(active, mode) : null), [active, mode])

  return {
    scn, scnB, mode, setMode, results, active, status, backend, patch, selectSite, setLatLon, jumpToWindow,
    selectSiteB, setLatLonB, compareOpen, setCompareOpen, bLoc,
    fly, requestFly, activePreset, toast, showToast, ranking, liveScore, showPresets, setShowPresets, panels, togglePanel,
    playing, setPlaying, speed, setSpeed: setSpeedState,
  }
}
