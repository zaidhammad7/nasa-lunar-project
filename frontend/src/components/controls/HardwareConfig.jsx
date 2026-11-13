import { useEffect, useMemo, useState } from 'react'
import { Label } from '../ui/primitives.jsx'
import { towerBoostDeg, sunDiscFraction, MAX_TOWER_M } from '../../lib/physics.js'

/** Tower height (numeric input, 1-150 m), panel tilt slider (0-90 deg) and panel area slider (1-50 m2). */
export default function HardwareConfig({ scenario, onPatch, calc }) {
  const [tower, setTower] = useState(String(scenario.tower))
  useEffect(() => { setTower(String(scenario.tower)) }, [scenario.tower])
  const t = parseFloat(tower), bad = tower !== '' && !(t >= 1 && t <= MAX_TOWER_M)
  const commit = () => {
    if (!(t >= 1)) return setTower(String(scenario.tower))
    const v = Math.min(MAX_TOWER_M, Math.max(1, Math.round(t * 2) / 2))
    setTower(String(v)); onPatch({ tower: v })
  }

  // tilt maximising the flux-weighted sin(el + tilt):  90 deg - atan(sum f sin(el) / sum f cos(el))
  const optimal = useMemo(() => {
    if (!calc) return null
    let A = 0, B = 0
    for (let i = 0; i < calc.n; i++) { const f = sunDiscFraction(calc.sunEff[i]), r = (calc.sunEff[i] * Math.PI) / 180; A += f * Math.cos(r); B += f * Math.sin(r) }
    return A > 0 ? Math.min(90, Math.max(0, 90 - (Math.atan(B / A) * 180) / Math.PI)) : null
  }, [calc])

  return (
    <div className="space-y-3.5">
      <label className="block">
        <Label right={<span className="num text-[10px]">horizon +{towerBoostDeg(scenario.tower).toFixed(3)}°</span>}>Tower height (m)</Label>
        <input type="number" min="1" max={MAX_TOWER_M} step="0.5" value={tower} onChange={(e) => setTower(e.target.value)} onBlur={commit}
          onKeyDown={(e) => e.key === 'Enter' && commit()} className={`num w-full ${bad ? '!border-nogo' : ''}`} aria-invalid={bad} aria-label="Tower height in metres" />
      </label>
      <div>
        <Label right={<span className="num text-xs text-ink">{scenario.tilt}°</span>}>Panel tilt (0° flat – 90° vertical)</Label>
        <input type="range" min={0} max={90} step={1} value={scenario.tilt} onChange={(e) => onPatch({ tilt: +e.target.value })} aria-label="Panel tilt"
          style={{ '--thumb': '#f59e0b', '--track': `linear-gradient(90deg,#f59e0b ${(scenario.tilt / 90) * 100}%,#334155 ${(scenario.tilt / 90) * 100}%)` }} />
        {optimal != null && (
          <div className="flex items-center justify-between text-[10px] text-mute">
            <span>optimal ≈ 90° − Sun elevation = <span className="num text-solar">{optimal.toFixed(1)}°</span></span>
            <button onClick={() => onPatch({ tilt: Math.round(optimal) })} className="rounded border border-line px-1.5 py-0.5 text-solar hover:bg-panel2">use</button>
          </div>
        )}
      </div>
      <div>
        <Label right={<span className="num text-xs text-ink">{scenario.area} m²</span>}>Panel area (m²)</Label>
        <input type="range" min={1} max={50} step={1} value={scenario.area} onChange={(e) => onPatch({ area: +e.target.value })} aria-label="Panel area"
          style={{ '--thumb': '#f59e0b', '--track': `linear-gradient(90deg,#f59e0b ${((scenario.area - 1) / 49) * 100}%,#334155 ${((scenario.area - 1) / 49) * 100}%)` }} />
      </div>
    </div>
  )
}
