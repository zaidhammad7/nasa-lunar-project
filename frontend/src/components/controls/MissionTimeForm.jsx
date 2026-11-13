import { useEffect, useRef, useState } from 'react'
import { BASELINE_START_MS, BASELINE_END_MS, HOUR_MS, iso } from '../../lib/physics.js'
import { Label } from '../ui/primitives.jsx'
import { cx } from '../../lib/format.js'

const MONTHS = [{ y: 2026, m: 10, name: 'November 2026' }, { y: 2026, m: 11, name: 'December 2026' }, { y: 2027, m: 0, name: 'January 2027' }]
const DOW = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const dayStart = (y, m, d) => Date.UTC(y, m, d)

/** Dark-mode calendar popup limited to the Nov 2026 - Jan 2027 ephemeris window. */
function CalendarPopup({ valueMs, onPick, onClose }) {
  const sel = new Date(valueMs)
  const [mi, setMi] = useState(Math.max(0, MONTHS.findIndex((m) => m.y === sel.getUTCFullYear() && m.m === sel.getUTCMonth())))
  const ref = useRef()
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    const k = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('mousedown', h); document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [onClose])
  const { y, m, name } = MONTHS[mi]
  const first = new Date(Date.UTC(y, m, 1)).getUTCDay(), days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate()
  const cells = [...Array(first).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)]
  const selDay = dayStart(sel.getUTCFullYear(), sel.getUTCMonth(), sel.getUTCDate())
  return (
    <div ref={ref} className="glass absolute z-40 mt-1 w-64 rounded-xl border border-line p-3 shadow-2xl" role="dialog" aria-label="Pick start date">
      <div className="mb-2 flex items-center justify-between">
        <button disabled={mi === 0} onClick={() => setMi(mi - 1)} className="rounded px-2 py-0.5 text-mute enabled:hover:bg-panel2 disabled:opacity-30" aria-label="Previous month">‹</button>
        <span className="text-xs font-semibold">{name}</span>
        <button disabled={mi === 2} onClick={() => setMi(mi + 1)} className="rounded px-2 py-0.5 text-mute enabled:hover:bg-panel2 disabled:opacity-30" aria-label="Next month">›</button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-[10px] text-mute">{DOW.map((d) => <div key={d} className="py-1">{d}</div>)}</div>
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((d, i) => {
          if (d == null) return <div key={`e${i}`} />
          const ms = dayStart(y, m, d), ok = ms >= BASELINE_START_MS && ms < BASELINE_END_MS
          return (
            <button key={d} disabled={!ok} onClick={() => { onPick(ms); onClose() }}
              className={cx('num h-8 rounded-md text-xs transition-colors', ms === selDay ? 'bg-earth font-bold text-bg' : ok ? 'text-ink hover:bg-panel2' : 'text-line')}>{d}</button>
          )
        })}
      </div>
      <p className="mt-2 text-[10px] text-mute">Window: 13 Nov 2026 – 12 Jan 2027 (UTC)</p>
    </div>
  )
}

/** Start date (calendar popup), start time (UTC) and mission duration in days, clamped to the ephemeris window. */
export default function MissionTimeForm({ scenario, onPatch }) {
  const startMs = Date.parse(scenario.startISO)
  const [open, setOpen] = useState(false)
  const dateStr = new Date(startMs).toISOString().slice(0, 10), timeStr = new Date(startMs).toISOString().slice(11, 16)
  const maxHours = Math.round((BASELINE_END_MS - startMs) / HOUR_MS)
  const days = +(scenario.durationHours / 24).toFixed(2)
  const [dur, setDur] = useState(String(days))
  useEffect(() => { setDur(String(days)) }, [days])

  const setStart = (ms) => {
    const c = Math.min(Math.max(ms, BASELINE_START_MS), BASELINE_END_MS - HOUR_MS)
    onPatch({ startISO: iso(c), durationHours: Math.min(scenario.durationHours, Math.round((BASELINE_END_MS - c) / HOUR_MS)) })
  }
  const commit = () => {
    const v = parseFloat(dur)
    if (!(v > 0)) return setDur(String(days))
    onPatch({ durationHours: Math.min(Math.max(1, Math.round(v * 24)), maxHours) })
  }

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2">
        <div className="relative">
          <Label>Start date</Label>
          <button onClick={() => setOpen((o) => !o)} className="num flex w-full items-center justify-between rounded-md border border-line bg-[#0f172a] px-2 py-1 text-[13px]" aria-haspopup="dialog">
            {dateStr}<span className="text-mute">▾</span>
          </button>
          {open && <CalendarPopup valueMs={startMs} onPick={(ms) => setStart(ms + (startMs % 86400000))} onClose={() => setOpen(false)} />}
        </div>
        <label className="block">
          <Label>Time (UTC)</Label>
          <input type="time" step={3600} value={timeStr} className="num w-full"
            onChange={(e) => { const [h] = e.target.value.split(':').map(Number); if (Number.isFinite(h)) setStart(Date.parse(`${dateStr}T00:00:00Z`) + h * HOUR_MS) }} />
        </label>
      </div>
      <label className="block">
        <Label right={<span className="num text-[10px]">max {(maxHours / 24).toFixed(1)} d</span>}>Duration (days)</Label>
        <input type="number" min="0.05" max={maxHours / 24} step="0.5" value={dur} onChange={(e) => setDur(e.target.value)} onBlur={commit}
          onKeyDown={(e) => e.key === 'Enter' && commit()} className="num w-full" />
      </label>
    </div>
  )
}
