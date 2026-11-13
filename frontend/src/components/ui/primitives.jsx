import { useState } from 'react'
import { cx } from '../../lib/format.js'

/** Collapsible drawer used for every control group / telemetry block in the left dashboard. */
export function Section({ title, icon, right, defaultOpen = true, accent = 'text-ink', children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="rounded-xl border border-line bg-panel/70">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left" aria-expanded={open}>
        <span className="text-sm">{icon}</span>
        <span className={cx('flex-1 text-[11px] font-semibold uppercase tracking-[0.14em]', accent)}>{title}</span>
        {right}
        <svg viewBox="0 0 20 20" className={cx('h-4 w-4 text-mute transition-transform', open && 'rotate-180')} fill="currentColor"><path d="M5.3 7.3a1 1 0 0 1 1.4 0L10 10.6l3.3-3.3a1 1 0 1 1 1.4 1.4l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 0-1.4z" /></svg>
      </button>
      {open && <div className="border-t border-line/70 px-3 pb-3 pt-2.5">{children}</div>}
    </section>
  )
}

export const Label = ({ children, right, className }) => (
  <div className={cx('mb-1 flex items-center justify-between text-[11px] text-mute', className)}><span>{children}</span>{right}</div>
)

export const Badge = ({ children, className }) => (
  <span className={cx('num inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide', className)}>{children}</span>
)

export function Stat({ label, value, unit, className, sub }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <div className={cx('num truncate text-base font-semibold leading-tight', className)}>{value}{unit && <span className="ml-0.5 text-[11px] font-normal text-mute">{unit}</span>}</div>
      {sub && <div className="num text-[10px] text-mute">{sub}</div>}
    </div>
  )
}

/** Horizontal bar used for sub-score breakdowns. */
export function Bar({ value, max = 100, color = '#38bdf8', label, valueLabel }) {
  return (
    <div className="mb-1.5">
      <div className="mb-0.5 flex justify-between text-[11px]"><span className="text-mute">{label}</span><span className="num text-ink">{valueLabel ?? value.toFixed(1)}</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-line/60"><div className="h-full rounded-full transition-all duration-300" style={{ width: `${Math.min(100, Math.max(0, (value / max) * 100))}%`, background: color }} /></div>
    </div>
  )
}
