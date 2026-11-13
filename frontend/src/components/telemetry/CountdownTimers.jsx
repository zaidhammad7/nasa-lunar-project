import { Section } from '../ui/primitives.jsx'
import { useTimeHours } from '../../lib/timeStore.js'
import { cx } from '../../lib/format.js'

/** "Xd Xh Xm" digital countdown block (tabular digits, so nothing jitters during scrubbing). */
export function Countdown({ title, ev, accent, compact }) {
  const none = !ev || ev.hours == null
  const [d, h, m] = none ? ['—', '—', '—'] : [ev.days, ev.hours_component, ev.minutes]
  return (
    <div className={cx('rounded-lg border border-line/80 bg-bg/60', compact ? 'px-2.5 py-1.5' : 'p-3')}>
      <div className="text-[10px] uppercase tracking-wider text-mute">{title}</div>
      <div className={cx('num font-semibold leading-tight', accent, compact ? 'text-lg' : 'text-2xl')}>
        {d}<span className="text-xs text-mute">d </span>{h}<span className="text-xs text-mute">h </span>{m}<span className="text-xs text-mute">m</span>
      </div>
      <div className="num truncate text-[10px] text-mute">{none ? ev?.note || 'no event in window' : new Date(ev.event_time_utc).toISOString().slice(5, 16).replace('T', ' ') + ' UTC'}</div>
    </div>
  )
}

export const countdownTitles = (sun, earth) => ({
  sun: sun?.currently_above_horizon ? 'Time to Sunset' : 'Time to Sunrise',
  earth: earth?.currently_above_horizon ? 'Time to Earthset' : 'Time to Earthrise',
})

/** Critical countdowns: Time to Sunset (or Sunrise if dark) and Time to Earthset (or Earthrise if blocked). */
export default function CountdownTimers({ calc }) {
  const h = useTimeHours(100)
  if (!calc) return null
  const { sun, earth } = calc.countdown(h)
  const t = countdownTitles(sun, earth)
  return (
    <Section title="Critical countdowns" icon="⏱" accent="text-ink">
      <div className="grid grid-cols-2 gap-2.5">
        <Countdown title={t.sun} ev={sun} accent="text-solar" />
        <Countdown title={t.earth} ev={earth} accent="text-earth" />
      </div>
      <p className="mt-1.5 text-[10px] text-mute">Exact horizon crossings (≈1 min resolution) scanned forward from the timeline position.</p>
    </Section>
  )
}
