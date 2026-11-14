import { useMemo } from 'react'
import { Card, Badge } from '../ui/primitives.jsx'
import { simulateBattery, requiredCapacityKwh, longestDarkHours } from '../../lib/survival.js'
import { fmt, cx } from '../../lib/format.js'


const Num = ({ label, unit, value, onChange, min, max, step }) => (
  <label className="block min-w-0">
    <span className="mb-1 block text-[10.5px] text-mute">{label} ({unit})</span>
    <input type="number" className="num w-full" value={value} min={min} max={max} step={step}
      onChange={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v) && v >= min && v <= max) onChange(v) }} />
  </label>
)

/** Does the lander's battery carry it through the longest night of this mission window? */
export default function SurvivalCard({ calc, scn, onPatch }) {
  const capacity = scn.batteryKwh, load = scn.loadW // kWh usable, W constant (avionics + survival heaters); shared with the map
  const setCapacity = (v) => onPatch({ batteryKwh: v }), setLoad = (v) => onPatch({ loadW: v })
  const r = useMemo(() => {
    const sim = simulateBattery(calc.power, capacity, load)
    return { ...sim, need: requiredCapacityKwh(calc.power, load), dark: longestDarkHours(calc.power) }
  }, [calc, capacity, load])
  const ok = r.survives
  return (
    <Card title="Power survival" right={<Badge className={cx(ok ? 'border-go/50 bg-go/10 text-go' : 'border-nogo/50 bg-nogo/10 text-nogo')}>{ok ? 'SURVIVES' : 'BATTERY DEPLETED'}</Badge>}>
      <div className="grid grid-cols-2 gap-2">
        <Num label="Battery" unit="kWh" value={capacity} onChange={setCapacity} min={1} max={2000} step={5} />
        <Num label="Constant load" unit="W" value={load} onChange={setLoad} min={10} max={20000} step={10} />
      </div>
      <div className="num mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
        <span className="text-mute">Longest night</span><span className="text-right text-ink">{r.dark} h</span>
        <span className="text-mute">Lowest charge</span><span className={cx('text-right', ok ? 'text-ink' : 'text-nogo')}>{fmt(r.minSocPct, 0)}%</span>
        <span className="text-mute">Hours without power</span><span className={cx('text-right', r.hoursEmpty ? 'text-nogo' : 'text-ink')}>{r.hoursEmpty} h</span>
        <span className="text-mute">Battery needed</span><span className="text-right text-ink">{Number.isFinite(r.need) ? `${fmt(r.need, 1)} kWh` : '> 5,000 kWh'}</span>
      </div>
      <p className="mt-2 text-[10.5px] leading-snug text-mute">Hourly energy balance of this site's solar power (current tilt, area and tower) against a constant load, starting fully charged.</p>
    </Card>
  )
}
