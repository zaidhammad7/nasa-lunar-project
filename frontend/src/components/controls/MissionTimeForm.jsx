import { useEffect, useMemo, useRef, useState } from 'react'
import { BASELINE_START_MS, BASELINE_END_MS, HOUR_MS, iso } from '../../lib/physics.js'
import { Label } from '../ui/primitives.jsx'
import { cx } from '../../lib/format.js'

const MONTHS = [{ y: 2026, m: 10, name: 'November 2026' }, { y: 2026, m: 11, name: 'December 2026' }, { y: 2027, m: 0, name: 'January 2027' }]
const DOW = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const dayStart = (y, m, d) => Date.UTC(y, m, d)

/** Dark-mode calendar popup limited to the Nov 2026 - Jan 2027 ephemeris window. */
function CalendarPopup({ valueMs, onPick, onClose }) {
  const sel = new Date(valueMs)
  const startIdx = Math.max(0, MONTHS.findIndex((m) => m.y === sel.getUTCFullYear() && m.m === sel.getUTCMonth()))
  const [mi, setMi] = useState(startIdx)
  const ref = useRef()
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    const k = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('mousedown', h); document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [onClose])
  const { y, m, name } = MONTHS[mi]
  const first = new Date(Date.UTC(y, m, 1)).getUTCDay()
  const days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate()
  const cells = [...Array(first).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)]
  const selDay = dayStart(sel.getUTCFullYear(), sel.getUTCMonth(), sel.getUTCDate())
  return (
    <div ref={ref} className="glass absolute z-30 mt-1 w-64 rounded-xl border border-line p-3 shadow-2xl" role="dialog" aria-label="Pick start date">
      <div className="mb-2 flex items-center justify-between">
        <button disabled={mi === 0} onClick={() => setMi(mi - 1)} className="rounded px-2 py-0.5 text-mute enabled:hover:bg-panel2 disabled:opacity-30" aria-label="Previous month">‹</button>
        <span className="text-xs font-semibold">{name}</span>
        <button disabled={mi === 2} onClick={() => setMi(mi + 1)} className="rounded px-2 py-0.5 text-mute enabled:hover:bg-panel2 disabled:opacity-30" aria-label="Next month">›</button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-[10px] text-mute">{DOW.map((d) => <div key={d} className="py-1">{d}</div>)}</div>
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((d, i) => {
          if (d == null) return <div key={`e${i}`} />
          const ms = dayStart(y, m, d)
          const ok = ms >= BASELINE_START_MS && ms < BASELINE_END_MS
          const isSel = ms === selDay
          return (
            <button key={d} disabled={!ok} onClick={() => { onPick(ms); onClose() }}
              className={cx('num h-8 rounded-md text-xs transition-colors', isSel ? 'bg-earth font-bold text-bg' : ok ? 'text-ink hover:bg-panel2' : 'text-line')}>
              {d}
            </button>
          )
        })}
      </div>
      <p className="mt-2 text-[10px] text-mute">Ephemeris window: 13 Nov 2026 – 12 Jan 2027 (UTC)</p>
    </div>
  )
}

/** Start date (calendar popup) + UTC time + mission duration (hours or days), clamped to the ephemeris window. */
export default function MissionTimeForm({ scenario, onPatch }) {
  const startMs = Date.parse(scenario.startISO)
  const [open, setOpen] = useState(false)
  const [unit, setUnit] = useState('days')
  const dateStr = new Date(startMs).toISOString().slice(0, 10)
  const timeStr = new Date(startMs).toISOString().slice(11, 16)
  const maxHours = Math.round((BASELINE_END_MS - startMs) / HOUR_MS)
  const durText = unit === 'days' ? +(scenario.durationHours / 24).toFixed(2) : scenario.durationHours
  const [dur, setDur] = useState(String(durText))
  useEffect(() => { setDur(String(durText)) }, [durText])

  const setStart = (ms) => {
    const clamped = Math.min(Math.max(ms, BASELINE_START_MS), BASELINE_END_MS - HOUR_MS)
    const maxH = Math.round((BASELINE_END_MS - clamped) / HOUR_MS)
    onPatch({ startISO: iso(clamped), durationHours: Math.min(scenario.durationHours, maxH) })
  }
  const commitDur = () => {
    const v = parseFloat(dur)
    if (!(v > 0)) return setDur(String(durText))
    onPatch({ durationHours: Math.min(Math.max(1, Math.round(unit === 'days' ? v * 24 : v)), maxHours) })
  }
  const presets = useMemo(() => [['24 h', 24], ['7 d', 168], ['14 d', 336], ['Full 60 d', 1440]], [])

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-5 gap-2">
        <div className="relative col-span-3">
          <Label>Start date (UTC)</Label>
          <button onClick={() => setOpen((o) => !o)} className="num flex w-full items-center justify-between rounded-md border border-line bg-[#0f172a] px-2 py-1 text-[13px]" aria-haspopup="dialog">
            {dateStr}<span className="text-mute">▾</span>
          </button>
          {open && <CalendarPopup valueMs={startMs} onPick={(ms) => setStart(ms + (startMs % 86400000))} onClose={() => setOpen(false)} />}
        </div>
        <label className="col-span-2 block">
          <Label>Time (UTC)</Label>
          <input type="time" step={3600} value={timeStr} className="num w-full"
            onChange={(e) => { const [h] = e.target.value.split(':').map(Number); if (Number.isFinite(h)) setStart(Date.parse(`${dateStr}T00:00:00Z`) + h * HOUR_MS) }} />
        </label>
      </div>
      <div>
        <Label right={<span className="num text-[10px]">max {maxHours} h ({(maxHours / 24).toFixed(1)} d) from this start</span>}>Mission duration</Label>
        <div className="flex gap-2">
          <input type="number" min={unit === 'days' ? 0.05 : 1} max={unit === 'days' ? maxHours / 24 : maxHours} step={unit === 'days' ? 0.5 : 1} value={dur}
            onChange={(e) => setDur(e.target.value)} onBlur={commitDur} onKeyDown={(e) => e.key === 'Enter' && commitDur()} className="num w-full" />
          <select value={unit} onChange={(e) => setUnit(e.target.value)}><option value="days">days</option><option value="hours">hours</option></select>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {presets.map(([l, h]) => (
            <button key={l} onClick={() => onPatch({ durationHours: Math.min(h, maxHours) })}
              className={cx('num rounded border px-1.5 py-0.5 text-[10px]', scenario.durationHours === Math.min(h, maxHours) ? 'border-earth text-earth' : 'border-line text-mute hover:text-ink')}>{l}</button>
          ))}
        </div>
      </div>
    </div>
  )
}
