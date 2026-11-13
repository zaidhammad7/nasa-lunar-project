import { useMemo } from 'react'
import { timeStore, useTimeHours } from '../../lib/timeStore.js'
import { fmtUtc } from '../../lib/format.js'
import { cx } from '../../lib/format.js'

const SPEEDS = [1, 10, 60]

/** CSS gradient with one stop per ~hour bucket, coloured by `colorAt(i)`. */
function strip(n, colorAt, buckets = 160) {
  const stops = []
  for (let b = 0; b < buckets; b++) {
    const i = Math.min(n - 1, Math.floor(((b + 0.5) / buckets) * n))
    const c = colorAt(i)
    stops.push(`${c} ${((b / buckets) * 100).toFixed(2)}% ${(((b + 1) / buckets) * 100).toFixed(2)}%`)
  }
  return `linear-gradient(90deg, ${stops.join(',')})`
}

/** Bottom scrubber: play / pause, 1x / 10x / 60x (1x = 1 simulated hour per second), Sun and Earth availability strips. */
export default function TimelineBar({ calc, playing, speed, onPlay, onSpeed, startMs, length }) {
  const h = useTimeHours(50)
  const idx = Math.floor(h)
  const sunStrip = useMemo(() => (calc ? strip(calc.n, (i) => (calc.state[i] === 2 ? '#f59e0b' : calc.state[i] === 1 ? '#92602b' : '#1e293b')) : 'none'), [calc])
  const earthStrip = useMemo(() => (calc ? strip(calc.n, (i) => (calc.earthEff[i] > 0 ? '#38bdf8' : '#7f1d3a')) : 'none'), [calc])
  const nowMs = startMs + h * 3600_000
  const day = Math.floor(h / 24)
  return (
    <div className="glass border-t border-line px-4 pb-2.5 pt-2">
      <div className="flex items-center gap-4">
        <button onClick={onPlay} aria-label={playing ? 'Pause' : 'Play'}
          className={cx('flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition-colors', playing ? 'border-solar bg-solar/15 text-solar' : 'border-earth bg-earth/15 text-earth hover:bg-earth/25')}>
          {playing
            ? <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor"><rect x="4" y="3" width="4" height="14" rx="1" /><rect x="12" y="3" width="4" height="14" rx="1" /></svg>
            : <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor"><path d="M6 3.5v13a1 1 0 0 0 1.5.9l10.5-6.5a1 1 0 0 0 0-1.8L7.5 2.6A1 1 0 0 0 6 3.5z" /></svg>}
        </button>
        <div className="flex shrink-0 overflow-hidden rounded-md border border-line">
          {SPEEDS.map((s) => (
            <button key={s} onClick={() => onSpeed(s)} className={cx('num px-2.5 py-1 text-xs', speed === s ? 'bg-earth/20 font-bold text-earth' : 'text-mute hover:bg-panel2')}>{s}x</button>
          ))}
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-baseline justify-between">
            <span className="num text-sm font-semibold text-ink">{fmtUtc(nowMs)}</span>
            <span className="num text-[11px] text-mute">hour {idx} / {Math.max(length - 1, 0)} · day {day + 1} of {Math.ceil(length / 24)}</span>
          </div>
          <div className="relative">
            <div className="mb-0.5 flex items-center gap-1.5"><span className="w-8 text-[9px] uppercase text-solar">Sun</span><div className="h-1.5 flex-1 rounded-sm" style={{ background: sunStrip }} /></div>
            <div className="mb-1 flex items-center gap-1.5"><span className="w-8 text-[9px] uppercase text-earth">Earth</span><div className="h-1.5 flex-1 rounded-sm" style={{ background: earthStrip }} /></div>
            <div className="flex items-center gap-1.5">
              <span className="w-8" />
              <input type="range" min={0} max={Math.max(length - 1, 1)} step={1} value={idx} aria-label="Mission timeline"
                onChange={(e) => timeStore.set(+e.target.value)} style={{ '--thumb': '#f1f5f9', '--track': '#334155' }} className="flex-1" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
