import { useEffect, useMemo, useState } from 'react'
import { Label } from '../ui/primitives.jsx'
import { towerBoostDeg, sunDiscFraction } from '../../lib/physics.js'
import { fmtW, fmt } from '../../lib/format.js'

/** Tower height (NUMERIC input, 1-20 m), Panel tilt slider (0-90°, optimal marker), Panel area slider (1-50 m²). */
export default function HardwareConfig({ scenario, onPatch, calc }) {
  const [tower, setTower] = useState(String(scenario.tower))
  useEffect(() => { setTower(String(scenario.tower)) }, [scenario.tower])
  const t = parseFloat(tower)
  const badTower = tower !== '' && !(t >= 1 && t <= 20)
  const commit = () => {
    if (!(t >= 1)) return setTower(String(scenario.tower))
    const v = Math.min(20, Math.max(1, Math.round(t * 2) / 2))
    setTower(String(v)); onPatch({ tower: v })
  }

  // Tilt that maximises the flux-weighted sin(el + tilt): tilt* = 90° - atan(B / A), A = sum f cos(el), B = sum f sin(el)
  const optimalTilt = useMemo(() => {
    if (!calc) return null
    let A = 0, B = 0
    for (let i = 0; i < calc.n; i++) { const f = sunDiscFraction(calc.sunEff[i]); const r = (calc.sunEff[i] * Math.PI) / 180; A += f * Math.cos(r); B += f * Math.sin(r) }
    return A > 0 ? Math.min(90, Math.max(0, 90 - (Math.atan(B / A) * 180) / Math.PI)) : null
  }, [calc])

  return (
    <div className="space-y-3">
      <label className="block">
        <Label right={<span className="num text-[10px]">horizon +{towerBoostDeg(Number.isFinite(t) ? Math.min(20, Math.max(1, t)) : scenario.tower).toFixed(3)}°</span>}>Tower height (m)</Label>
        <div className="flex items-center gap-2">
          <input type="number" min="1" max="20" step="0.5" value={tower} onChange={(e) => setTower(e.target.value)} onBlur={commit}
            onKeyDown={(e) => e.key === 'Enter' && commit()} className={`num w-28 ${badTower ? '!border-nogo' : ''}`} aria-invalid={badTower} aria-label="Tower height in metres" />
          <span className="text-[10px] text-mute">type 1 – 20 m · raises arrays & antenna above the local horizon</span>
        </div>
      </label>

      <div>
        <Label right={<span className="num text-xs text-ink">{scenario.tilt}°</span>}>Panel tilt (0° flat – 90° vertical)</Label>
        <div className="relative">
          {optimalTilt != null && (
            <div className="pointer-events-none absolute -top-0.5 z-10 flex -translate-x-1/2 flex-col items-center" style={{ left: `calc(${(optimalTilt / 90) * 100}% + ${(0.5 - optimalTilt / 90) * 16}px)` }}>
              <span className="num text-[9px] font-semibold text-solar">▼ {optimalTilt.toFixed(1)}°</span>
            </div>
          )}
          <input type="range" min={0} max={90} step={1} value={scenario.tilt} onChange={(e) => onPatch({ tilt: +e.target.value })} aria-label="Panel tilt"
            style={{ '--thumb': '#f59e0b', '--track': `linear-gradient(90deg,#f59e0b ${(scenario.tilt / 90) * 100}%,#334155 ${(scenario.tilt / 90) * 100}%)`, marginTop: 10 }} />
        </div>
        <div className="flex items-center justify-between text-[10px] text-mute">
          <span>optimal ≈ 90° − Sun elevation{optimalTilt != null && <> = <span className="num text-solar">{optimalTilt.toFixed(1)}°</span></>}</span>
          {optimalTilt != null && <button onClick={() => onPatch({ tilt: Math.round(optimalTilt) })} className="rounded border border-line px-1.5 py-0.5 text-[10px] text-solar hover:bg-panel2">set optimal</button>}
        </div>
      </div>

      <div>
        <Label right={<span className="num text-xs text-ink">{scenario.area} m²</span>}>Panel area</Label>
        <input type="range" min={1} max={50} step={1} value={scenario.area} onChange={(e) => onPatch({ area: +e.target.value })} aria-label="Panel area"
          style={{ '--thumb': '#f59e0b', '--track': `linear-gradient(90deg,#f59e0b ${((scenario.area - 1) / 49) * 100}%,#334155 ${((scenario.area - 1) / 49) * 100}%)` }} />
      </div>

      {calc && (
        <div className="num grid grid-cols-3 gap-2 rounded-md border border-line/70 bg-bg/50 px-2 py-1.5 text-[10.5px]">
          <div><div className="text-mute">peak</div><div className="text-solar">{fmtW(calc.stats.peakPower)}</div></div>
          <div><div className="text-mute">mean</div><div className="text-solar">{fmtW(calc.stats.avgPower)}</div></div>
          <div><div className="text-mute">energy</div><div className="text-solar">{fmt(calc.stats.totalKwh, 0)} kWh</div></div>
        </div>
      )}
    </div>
  )
}
