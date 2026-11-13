import { Label } from '../ui/primitives.jsx'
import { effectiveMaxSlope, SLOPE_MARGIN_DEG } from '../../lib/physics.js'

function Slider({ label, value, min, max, step = 1, unit, onChange, color = '#38bdf8', extra, track }) {
  return (
    <div>
      <Label right={<span className="num text-xs text-ink">{value}{unit}</span>}>{label}</Label>
      <div className="relative">
        {extra}
        <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} aria-label={label}
          style={{ '--thumb': color, '--track': track }} />
      </div>
    </div>
  )
}

/** Max allowable slope (0-15°, with the safety-factor cutoff drawn), min Sun visibility, min Earth visibility. */
export default function VehicleFilters({ scenario, onPatch }) {
  const eff = effectiveMaxSlope(scenario.maxSlope)
  const pct = (v) => `${(v / 15) * 100}%`
  return (
    <div className="space-y-3">
      <Slider label="Max allowable slope" value={scenario.maxSlope} min={0} max={15} step={0.5} unit="°" color="#10b981" onChange={(v) => onPatch({ maxSlope: v })}
        track={`linear-gradient(90deg,#10b981 0%,#10b981 ${pct(eff)},#f59e0b ${pct(eff)},#f59e0b ${pct(scenario.maxSlope)},#334155 ${pct(scenario.maxSlope)},#334155 100%)`} />
      <div className="num -mt-1.5 flex items-center justify-between rounded-md border border-line/70 bg-bg/50 px-2 py-1 text-[10.5px]">
        <span className="text-mute">Operational cutoff (FS {eff > 0 ? (scenario.maxSlope / eff).toFixed(2) : '—'})</span>
        <span className="font-semibold text-solar">{eff.toFixed(1)}° <span className="font-normal text-mute">= {scenario.maxSlope}° − {SLOPE_MARGIN_DEG}° margin</span></span>
      </div>
      <Slider label="Min solar visibility" value={scenario.minSun} min={0} max={100} unit="%" color="#f59e0b" onChange={(v) => onPatch({ minSun: v })}
        track={`linear-gradient(90deg,#f59e0b ${scenario.minSun}%,#334155 ${scenario.minSun}%)`} />
      <Slider label="Min Earth visibility" value={scenario.minEarth} min={0} max={100} unit="%" color="#38bdf8" onChange={(v) => onPatch({ minEarth: v })}
        track={`linear-gradient(90deg,#38bdf8 ${scenario.minEarth}%,#334155 ${scenario.minEarth}%)`} />
    </div>
  )
}
