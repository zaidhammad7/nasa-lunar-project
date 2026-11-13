import { cx } from '../../lib/format.js'

/** Plain titled card used by every group of controls / results (no accordions: nothing is hidden or nested). */
export function Card({ title, icon, right, accent = 'text-mute', className, children }) {
  return (
    <section className={cx('rounded-xl border border-line bg-panel/70 p-3.5', className)}>
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          <h2 className={cx('flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em]', accent)}>{icon && <span>{icon}</span>}{title}</h2>
          {right}
        </header>
      )}
      {children}
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
      <div className={cx('num truncate text-lg font-semibold leading-tight', className)}>{value}{unit && <span className="ml-0.5 text-[11px] font-normal text-mute">{unit}</span>}</div>
      {sub && <div className="num truncate text-[10px] text-mute">{sub}</div>}
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
