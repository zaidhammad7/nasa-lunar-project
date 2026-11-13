import { MODES, MODE_KEYS } from '../../lib/physics.js'
import { cx } from '../../lib/format.js'

const ACCENT = { most_safety: '#10b981', balanced: '#38bdf8', most_power: '#f59e0b' }

/** MOST SAFETY | BALANCED | MOST POWER segmented control (re-weights terrain / solar / comms). */
export default function OptimizationSlider({ mode, onChange }) {
  const [wt, ws, wc] = MODES[mode].w
  return (
    <div>
      <div className="grid grid-cols-3 gap-1 rounded-lg border border-line bg-bg/60 p-1" role="radiogroup" aria-label="Optimization priority">
        {MODE_KEYS.map((k) => (
          <button key={k} role="radio" aria-checked={k === mode} onClick={() => onChange(k)}
            className={cx('rounded-md px-1 py-1.5 text-center text-[10.5px] font-semibold tracking-wide transition-colors', k === mode ? 'bg-panel2' : 'text-mute hover:text-ink')}
            style={k === mode ? { color: ACCENT[k], boxShadow: `inset 0 0 0 1px ${ACCENT[k]}` } : undefined}>
            {MODES[k].label}
          </button>
        ))}
      </div>
      <div className="num mt-1.5 text-center text-[10.5px] text-mute">terrain {Math.round(wt * 100)}% · solar {Math.round(ws * 100)}% · comms {Math.round(wc * 100)}%</div>
    </div>
  )
}
