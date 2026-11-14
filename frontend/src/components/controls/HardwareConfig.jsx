import { useEffect, useMemo, useState } from 'react'
import { Label } from '../ui/primitives.jsx'
import { towerBoostDeg, horizonDistanceKm, sunDiscFraction, MAX_TOWER_M, effectiveMaxSlope } from '../../lib/physics.js'
import { checkRange } from '../../lib/validation.js'
import { GLOSSARY } from '../../lib/glossary.js'
import InfoTip from '../ui/InfoTip.jsx'

/** Tower height (numeric input, 1-150 m), panel tilt slider (0-90 deg) and panel area slider (1-50 m2). */
export default function HardwareConfig({ scenario, onPatch, calc, terrain }) {
  const [tower, setTower] = useState(String(scenario.tower))
  useEffect(() => { setTower(String(scenario.tower)) }, [scenario.tower])
  const t = parseFloat(tower), issue = tower === '' ? null : checkRange('tower', tower), bad = !!issue
  const commit = () => {
    if (!(t >= 1)) return setTower(String(scenario.tower))
    const v = Math.min(MAX_TOWER_M, Math.max(1, Math.round(t * 2) / 2))
    setTower(String(v)); onPatch({ tower: v })
  }

  // What the current tower height does, re-derived instantly from the hourly Sun / Earth elevations (no mast = elevations minus the dip)
  const effect = useMemo(() => {
    if (!calc) return null
    const dip = calc.boost
    let sun0 = 0, earth0 = 0
    for (let i = 0; i < calc.n; i++) { if (calc.sunEff[i] - dip > 0) sun0++; if (calc.earthEff[i] - dip > 0) earth0++ }
    return { sun: calc.stats.sunVisPct, dSun: calc.stats.sunVisPct - (sun0 / calc.n) * 100, earth: calc.stats.earthVisPct, dEarth: calc.stats.earthVisPct - (earth0 / calc.n) * 100 }
  }, [calc])
  const slope = terrain?.Slope_deg, limit = effectiveMaxSlope(scenario.maxSlope ?? 15)
  const sg = (v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}`

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
        <Label right={<span className="num text-[10px]">horizon dip +{towerBoostDeg(scenario.tower).toFixed(3)}°</span>}>
          <span>Tower height (m) <InfoTip text={GLOSSARY.tower} /></span></Label>
        <input type="number" min="1" max={MAX_TOWER_M} step="0.5" value={tower} onChange={(e) => setTower(e.target.value)} onBlur={commit}
          onKeyDown={(e) => e.key === 'Enter' && commit()} className={`num w-full ${bad ? '!border-nogo' : ''}`} aria-invalid={bad} aria-label="Tower height in metres" />
        {bad && <p role="alert" className="mt-1 text-[10.5px] text-nogo">{issue.message}</p>}
      </label>
      <div className="num space-y-0.5 rounded-lg border border-line/70 bg-bg/40 px-2.5 py-2 text-[10.5px] leading-snug text-mute" aria-live="polite">
        <div className="flex items-center justify-between"><span>Line of sight to horizon <InfoTip text={GLOSSARY.horizon} /></span><span className="text-ink">{horizonDistanceKm(scenario.tower).toFixed(1)} km</span></div>
        {effect && <>
          <div className="flex justify-between"><span>Sunlight</span><span className="text-solar">{effect.sun.toFixed(1)}% <span className="text-mute">({sg(effect.dSun)} vs no mast)</span></span></div>
          <div className="flex justify-between"><span>Earth comms</span><span className="text-earth">{effect.earth.toFixed(1)}% <span className="text-mute">({sg(effect.dEarth)} vs no mast)</span></span></div>
        </>}
        {slope != null && <div className="flex justify-between"><span>Slope vs {limit.toFixed(1)}° limit</span><span className="text-ink">{slope.toFixed(2)}° · unchanged by tower</span></div>}
      </div>
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
