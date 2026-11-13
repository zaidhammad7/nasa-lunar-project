import { useCallback, useMemo, useRef } from 'react'
import DashboardShell from './components/layout/DashboardShell.jsx'
import TopHeader from './components/layout/TopHeader.jsx'
import KpiRibbon from './components/layout/KpiRibbon.jsx'
import SiteSelector from './components/controls/SiteSelector.jsx'
import OptimizationSlider from './components/controls/OptimizationSlider.jsx'
import MissionTimeForm from './components/controls/MissionTimeForm.jsx'
import VehicleFilters from './components/controls/VehicleFilters.jsx'
import HardwareConfig from './components/controls/HardwareConfig.jsx'
import TimelineBar from './components/controls/TimelineBar.jsx'
import LunarViewport from './components/scene3d/LunarViewport.jsx'
import LightStatusCard from './components/telemetry/LightStatusCard.jsx'
import CommsStatusCard from './components/telemetry/CommsStatusCard.jsx'
import PowerMetricsCard from './components/telemetry/PowerMetricsCard.jsx'
import CountdownTimers from './components/telemetry/CountdownTimers.jsx'
import XaiDiagnosticsCard from './components/telemetry/XaiDiagnosticsCard.jsx'
import SmartWindowList from './components/telemetry/SmartWindowList.jsx'
import ComparisonModal from './components/telemetry/ComparisonModal.jsx'
import { Section } from './components/ui/primitives.jsx'
import { useLunarSimulation } from './hooks/useLunarSimulation.js'
import { useSolarPowerCalc } from './hooks/useSolarPowerCalc.js'
import { useCsvExporter } from './hooks/useCsvExporter.js'
import { useTimeMeta, timeStore } from './lib/timeStore.js'
import { warmup } from './api/lunarModelApi.js'
import { cx } from './lib/format.js'

const PIN = { A: '#38bdf8', B: '#a78bfa' }

export default function App() {
  const sim = useLunarSimulation()
  const { scn, results, editing, compareOn, activeScn, active, mode } = sim

  const hwA = useMemo(() => ({ tower: scn.A.tower, tilt: scn.A.tilt, area: scn.A.area }), [scn.A.tower, scn.A.tilt, scn.A.area])
  const hwB = useMemo(() => ({ tower: scn.B.tower, tilt: scn.B.tilt, area: scn.B.area }), [scn.B.tower, scn.B.tilt, scn.B.area])
  const calcA = useSolarPowerCalc(results.A, hwA)
  const calcB = useSolarPowerCalc(compareOn ? results.B : null, hwB)
  const calc = editing === 'B' && compareOn ? calcB : calcA
  const hw = editing === 'B' && compareOn ? hwB : hwA
  const calcRef = useRef({ A: null, B: null })
  calcRef.current = { A: calcA, B: calcB }

  const meta = useTimeMeta()
  const csv = useCsvExporter(activeScn, mode, active, calc)

  // ---- 3-D scene inputs
  const pins = useMemo(() => {
    const list = [{ key: 'A', lat: scn.A.lat, lon: scn.A.lon, color: PIN.A, label: `A · ${(scn.A.siteId || 'custom').replace('Auto_', '')}`, tower: scn.A.tower, tilt: scn.A.tilt }]
    if (compareOn) list.push({ key: 'B', lat: scn.B.lat, lon: scn.B.lon, color: PIN.B, label: `B · ${(scn.B.siteId || 'custom').replace('Auto_', '')}`, tower: scn.B.tower, tilt: scn.B.tilt })
    return list
  }, [scn.A.lat, scn.A.lon, scn.A.siteId, scn.A.tower, scn.A.tilt, scn.B.lat, scn.B.lon, scn.B.siteId, scn.B.tower, scn.B.tilt, compareOn])
  const getLive = useCallback((key) => () => {
    const c = calcRef.current[key]
    return c ? c.at(timeStore.hours) : { lit: false, connected: false }
  }, [])
  const rays = useMemo(() => pins.map((p) => ({ key: p.key, lat: p.lat, lon: p.lon, tower: p.tower, getLive: getLive(p.key) })), [pins, getLive])

  const onWarmup = useCallback(async () => {
    sim.showToast('Warming up DEM + demo sites…')
    try { const r = await warmup(); sim.showToast(`Warm-up done in ${Math.round(r.total_ms)} ms · cache ${r.cached_demo_sites}/5 · DEM ${r.dem_ready ? 'ready' : 'unavailable'}`) } catch (e) { sim.showToast(`Warm-up failed: ${e.message}`) }
  }, [sim])

  const sidebar = (
    <>
      <Section title="Location" icon="📍" accent="text-earth"
        right={compareOn && <span className="num text-[10px]" style={{ color: PIN[editing] }}>editing {editing}</span>}>
        {compareOn && (
          <div className="mb-2.5 grid grid-cols-2 gap-1 rounded-lg border border-line bg-bg/60 p-1">
            {['A', 'B'].map((k) => (
              <button key={k} onClick={() => sim.setEditing(k)} className={cx('rounded-md px-2 py-1.5 text-[11px] font-semibold transition-colors', editing === k ? 'bg-panel2' : 'text-mute hover:text-ink')}
                style={editing === k ? { color: PIN[k], boxShadow: `inset 0 0 0 1px ${PIN[k]}` } : undefined}>
                Site {k} <span className="num font-normal text-mute">{scn[k].siteId || 'custom'}</span>
              </button>
            ))}
          </div>
        )}
        <SiteSelector scenario={activeScn} label={compareOn ? `Site ${editing}` : 'Site A'} onSelect={sim.selectSite} onLatLon={(la, lo) => sim.setLatLon(la, lo)} />
      </Section>
      <Section title="Optimization priority" icon="🎚" accent="text-go"><OptimizationSlider mode={mode} onChange={sim.setMode} /></Section>
      <Section title="Mission window" icon="🗓" accent="text-ink"><MissionTimeForm scenario={activeScn} onPatch={sim.patch} /></Section>
      <Section title="Vehicle constraints" icon="🛰" accent="text-ink" defaultOpen={false}><VehicleFilters scenario={activeScn} onPatch={sim.patch} /></Section>
      <Section title="Solar hardware" icon="🔆" accent="text-solar"><HardwareConfig scenario={activeScn} onPatch={sim.patch} calc={calc} /></Section>

      <div className="px-1 pt-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-mute">Live telemetry & analytics</div>
      <CountdownTimers calc={calc} />
      <LightStatusCard calc={calc} />
      <CommsStatusCard calc={calc} />
      <PowerMetricsCard calc={calc} hw={hw} />
      <XaiDiagnosticsCard result={active} mode={mode} ranking={sim.ranking} onSelectSite={sim.selectSite} />
      <SmartWindowList result={active} onJump={sim.jumpToWindow} />
      <div className="pb-6 text-center text-[10px] text-mute">Data: LOLA 118 m DEM · JPL Horizons · ML + physics guardrails · {active?._source === 'offline' ? 'OFFLINE fallback' : 'live backend'}</div>
    </>
  )

  return (
    <DashboardShell
      header={<TopHeader backend={sim.backend} loading={sim.status.loading} error={sim.status.error} compareOn={compareOn} onToggleCompare={sim.toggleCompare}
        onExport={csv.exportCsv} exporting={csv.busy} onWarmup={onWarmup} />}
      sidebar={sidebar}
      ribbon={<KpiRibbon result={active} liveScore={sim.liveScore} calc={calc} />}
      viewport={<LunarViewport sites={sim.ranking.all} pins={pins} rays={rays} fly={sim.fly} activePreset={sim.activePreset}
        onPick={(la, lo) => sim.setLatLon(la, lo, { fromPick: true })} onSelectSite={sim.selectSite} onPreset={(k) => sim.requestFly(k, activeScn.lat, activeScn.lon)} />}
      overlay={<>
        {compareOn && <ComparisonModal results={results} scn={scn} onClose={sim.toggleCompare} />}
        {sim.toast && <div className="glass num absolute bottom-4 left-1/2 z-30 -translate-x-1/2 rounded-lg border border-line px-4 py-2 text-xs shadow-xl" role="status">{sim.toast}</div>}
        {csv.note && <div className="num absolute bottom-4 right-4 z-20 rounded-md border border-line bg-panel/90 px-3 py-1.5 text-[11px] text-mute">{csv.note}</div>}
      </>}
      timeline={<TimelineBar calc={calc} playing={sim.playing} speed={sim.speed} startMs={calc?.startMs ?? 0} length={meta.length}
        onPlay={() => sim.setPlaying(!sim.playing)} onSpeed={sim.setSpeed} />}
    />
  )
}
