import { MODES, MODE_KEYS } from '../../lib/physics.js'
import { cx } from '../../lib/format.js'

const ACCENT = { most_safety: '#10b981', balanced: '#38bdf8', most_power: '#f59e0b' }

/** MOST SAFETY / BALANCED / MOST POWER: 3-stop slider that re-weights the composite score (terrain / solar / comms). */
export default function OptimizationSlider({ mode, onChange }) {
  const idx = MODE_KEYS.indexOf(mode)
  const [wt, ws, wc] = MODES[mode].w
  return (
    <div>
      <div className="relative px-1 pt-1">
        <input type="range" min={0} max={2} step={1} value={idx} aria-label="Optimization priority"
          onChange={(e) => onChange(MODE_KEYS[+e.target.value])}
          style={{ '--thumb': ACCENT[mode], '--track': 'linear-gradient(90deg,#10b981 0%,#38bdf8 50%,#f59e0b 100%)' }} />
      </div>
      <div className="mt-1 grid grid-cols-3 gap-1">
        {MODE_KEYS.map((k) => (
          <button key={k} onClick={() => onChange(k)}
            className={cx('rounded-md border px-1 py-1.5 text-center text-[10.5px] font-semibold tracking-wide transition-colors', k === mode ? 'bg-panel2' : 'border-transparent text-mute hover:bg-panel2/60')}
            style={k === mode ? { borderColor: ACCENT[k], color: ACCENT[k] } : undefined}>
            {MODES[k].label}
          </button>
        ))}
      </div>
      <div className="mt-2.5 flex h-2 overflow-hidden rounded-full" title="terrain / solar / comms weights">
        <div style={{ width: `${wt * 100}%`, background: '#10b981' }} /><div style={{ width: `${ws * 100}%`, background: '#f59e0b' }} /><div style={{ width: `${wc * 100}%`, background: '#38bdf8' }} />
      </div>
      <div className="num mt-1 flex justify-between text-[10.5px]">
        <span className="text-go">Terrain {Math.round(wt * 100)}%</span><span className="text-solar">Solar {Math.round(ws * 100)}%</span><span className="text-earth">Comms {Math.round(wc * 100)}%</span>
      </div>
      <p className="mt-1.5 text-[10px] leading-snug text-mute">{MODES[mode].hint}. The GO / NO-GO safety verdict and the 13.5° safety factor are never relaxed by the mode.</p>
    </div>
  )
}
