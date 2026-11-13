import { Section, Stat } from '../ui/primitives.jsx'
import Sparkline from '../ui/Sparkline.jsx'
import { useTimeHours } from '../../lib/timeStore.js'
import { fmt, fmtW } from '../../lib/format.js'

/** Real-time electrical output (W) and accumulated mission energy (kWh); updates instantly with tower / tilt / area. */
export default function PowerMetricsCard({ calc, hw }) {
  const h = useTimeHours()
  if (!calc) return null
  const now = calc.at(h)
  return (
    <Section title="Power generation" icon="⚡" accent="text-solar">
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Real-time output" value={fmtW(now.power)} className="text-solar text-xl" sub={`${hw.area} m² · tilt ${hw.tilt}° · η 30%`} />
        <Stat label="Energy so far" value={fmt(now.cumKwh, 1)} unit="kWh" className="text-solar text-xl" sub={`of ${fmt(calc.stats.totalKwh, 0)} kWh total`} />
      </div>
      <div className="num mt-2 grid grid-cols-3 gap-2 text-[11px]">
        <div><span className="text-mute">peak </span><span className="text-ink">{fmtW(calc.stats.peakPower)}</span></div>
        <div><span className="text-mute">mean </span><span className="text-ink">{fmtW(calc.stats.avgPower)}</span></div>
        <div><span className="text-mute">total </span><span className="text-ink">{fmt(calc.stats.totalKwh, 0)} kWh</span></div>
      </div>
      <div className="mt-1"><Sparkline data={calc.power} color="#f59e0b" fill min={0} label="Power over the mission" /></div>
      <p className="text-[10px] text-mute">P = 1361 W/m² × 0.30 × area × disc fraction × max(0, sin(Sun el + tilt)) · panel tracks the Sun in azimuth</p>
    </Section>
  )
}
