import { useCallback, useMemo, useRef, useState } from 'react'
import DashboardShell from './components/layout/DashboardShell.jsx'
import TopHeader from './components/layout/TopHeader.jsx'
import PanelToggles from './components/layout/PanelToggles.jsx'
import SiteSelector from './components/controls/SiteSelector.jsx'
import OptimizationSlider from './components/controls/OptimizationSlider.jsx'
import MissionTimeForm from './components/controls/MissionTimeForm.jsx'
import HardwareConfig from './components/controls/HardwareConfig.jsx'
import ActionButtons from './components/controls/ActionButtons.jsx'
import TimelineBar from './components/controls/TimelineBar.jsx'
import LunarViewport from './components/scene3d/LunarViewport.jsx'
import ResultsPanel from './components/panels/ResultsPanel.jsx'
import ComparisonModal from './components/telemetry/ComparisonModal.jsx'
import { Card } from './components/ui/primitives.jsx'
import { useLunarSimulation } from './hooks/useLunarSimulation.js'
import { useSolarPowerCalc } from './hooks/useSolarPowerCalc.js'
import { useCsvExporter } from './hooks/useCsvExporter.js'
import { HEAT_RANGE, rampColor } from './lib/heatmap.js'
import { useTimeMeta, timeStore } from './lib/timeStore.js'
import { warmup } from './api/lunarModelApi.js'
import { sky } from './components/scene3d/sky.js'

const PIN = { A: '#38bdf8', B: '#a78bfa' }

export default function App() {
  const sim = useLunarSimulation()
  const { scn, scnB, results, mode, active, compareOpen } = sim

  const hwA = useMemo(() => ({ tower: scn.tower, tilt: scn.tilt, area: scn.area }), [scn.tower, scn.tilt, scn.area])
  const calc = useSolarPowerCalc(results.A, hwA)
  const calcB = useSolarPowerCalc(compareOpen ? results.B : null, hwA)
  const calcRef = useRef({ A: null, B: null })
  calcRef.current = { A: calc, B: calcB }
  const meta = useTimeMeta()
  const csv = useCsvExporter(scn, mode, active, calc, sim.liveScore)
  const [heatmap, setHeatmap] = useState(false)
  const [craters, setCraters] = useState(true)
  // Heatmap input: every scored site with its score in the current priority mode (re-interpolated when the mode changes)
  const heatSites = useMemo(() => (heatmap ? sim.ranking.all.map((s) => ({ lat: s.lat, lon: s.lon, score: s.modeScore })) : null), [heatmap, sim.ranking])

  // ---- 3-D scene inputs: Site A (and Site B while comparing)
  const pins = useMemo(() => {
    const label = (id) => (id ? id.replace('Auto_', '') : 'custom')
    const list = [{ key: 'A', lat: scn.lat, lon: scn.lon, color: PIN.A, label: `A · ${label(scn.siteId)}`, tower: scn.tower, tilt: scn.tilt }]
    if (compareOpen) list.push({ key: 'B', lat: scnB.lat, lon: scnB.lon, color: PIN.B, label: `B · ${label(scnB.siteId)}`, tower: scn.tower, tilt: scn.tilt })
    return list
  }, [scn.lat, scn.lon, scn.siteId, scn.tower, scn.tilt, scnB.lat, scnB.lon, scnB.siteId, compareOpen])
  const getLive = useCallback((key) => () => {
    const c = calcRef.current[key]
    return c ? c.at(timeStore.hours) : { lit: false, connected: false }
  }, [])
  const rays = useMemo(() => pins.map((p) => ({ key: p.key, lat: p.lat, lon: p.lon, tower: p.tower, getLive: getLive(p.key) })), [pins, getLive])

  const onWarmup = useCallback(async () => {
    sim.showToast('Preloading terrain data and reference sites…')
    try { const r = await warmup(); sim.showToast(`System ready in ${Math.round(r.total_ms)} ms · reference sites ${r.cached_demo_sites}/5 · terrain model ${r.dem_ready ? 'ready' : 'unavailable'}`) } catch (e) { sim.showToast(`Preload failed: ${e.message}`) }
  }, [sim])

  const onPreset = useCallback((kind) => {
    if (kind === 'sunearth') {
      const [s, e] = [sky.sun, sky.earth]
      const sep = (Math.acos(Math.max(-1, Math.min(1, s[0] * e[0] + s[1] * e[1] + s[2] * e[2]))) * 180) / Math.PI
      sim.showToast(`Sun–Earth separation as seen from the Moon: ${sep.toFixed(0)}°${sep > 85 ? ' — too wide for one view; scrub the timeline toward full Moon (hour ~300) to bring them together' : ''}`)
    }
    sim.requestFly(kind, scn.lat, scn.lon)
  }, [sim, scn.lat, scn.lon])

  const left = (
    <>
      <Card title="Location" icon="📍" accent="text-earth">
        <SiteSelector scenario={scn} onSelect={sim.selectSite} onLatLon={(la, lo) => sim.setLatLon(la, lo)} showPresets={sim.showPresets} onTogglePresets={() => sim.setShowPresets(!sim.showPresets)} />
        <div className="mt-2 space-y-2 text-[12.5px]">
          <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" checked={heatmap} onChange={(e) => setHeatmap(e.target.checked)} />Suitability heatmap</label>
          <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" checked={craters} onChange={(e) => setCraters(e.target.checked)} />Named craters (IAU)</label>
        </div>
      </Card>
      <Card title="Priority & mission time" icon="🎚" accent="text-go">
        <div className="space-y-4">
          <OptimizationSlider mode={mode} onChange={sim.setMode} />
          <MissionTimeForm scenario={scn} onPatch={sim.patch} />
        </div>
      </Card>
      <Card title="Solar hardware" icon="🔆" accent="text-solar"><HardwareConfig scenario={scn} onPatch={sim.patch} calc={calc} /></Card>
      <ActionButtons onCompare={() => sim.setCompareOpen(true)} onExport={csv.exportCsv} disabled={!calc} />
    </>
  )

  const viewport = (
    <div className="relative h-full w-full">
      <LunarViewport sites={sim.ranking.all} showPresets={sim.showPresets} pins={pins} rays={rays} fly={sim.fly} activePreset={sim.activePreset}
        onPick={(la, lo) => sim.setLatLon(la, lo, { fromPick: true })} onPreset={onPreset} heatSites={heatSites} showCraters={craters} />
      <PanelToggles panels={sim.panels} onToggle={sim.togglePanel} />
      {heatmap && (
        <div className="glass num absolute bottom-3 left-3 z-10 rounded-lg border border-line px-3 py-2 text-[10.5px] text-mute">
          <div className="mb-1 text-ink">Suitability score</div>
          <div className="h-2 w-40 rounded" style={{ background: `linear-gradient(90deg, rgb(${rampColor(HEAT_RANGE[0])}), rgb(${rampColor((HEAT_RANGE[0] + HEAT_RANGE[1]) / 2)}), rgb(${rampColor(HEAT_RANGE[1])}))` }} />
          <div className="mt-0.5 flex justify-between"><span>≤{HEAT_RANGE[0]}</span><span>≥{HEAT_RANGE[1]}</span></div>
          <div className="mt-1">interpolated from 100 scored sites</div>
        </div>
      )}
      {(sim.toast || csv.note) && <div className="glass num absolute bottom-3 left-1/2 z-20 -translate-x-1/2 rounded-lg border border-line px-4 py-2 text-xs shadow-xl" role="status">{sim.toast || csv.note}</div>}
    </div>
  )

  return (
    <>
      <DashboardShell
        panels={sim.panels}
        header={<TopHeader backend={sim.backend} loading={sim.status.loading} error={sim.status.error} onWarmup={onWarmup} />}
        left={left}
        viewport={viewport}
        timeline={<TimelineBar calc={calc} playing={sim.playing} speed={sim.speed} startMs={calc?.startMs ?? 0} length={meta.length}
          onPlay={() => sim.setPlaying(!sim.playing)} onSpeed={sim.setSpeed} />}
        right={<ResultsPanel result={active} calc={calc} scn={scn} mode={mode} liveScore={sim.liveScore} ranking={sim.ranking}
          onJump={sim.jumpToWindow} onSelectSite={sim.selectSite} onPatch={sim.patch} />}
      />
      {compareOpen && <ComparisonModal results={results} scnB={scnB} onSelectB={sim.selectSiteB} onLatLonB={sim.setLatLonB} onClose={() => sim.setCompareOpen(false)} />}
    </>
  )
}
