import { Card } from '../ui/primitives.jsx'
import { useTimeHours } from '../../lib/timeStore.js'
import { cx } from '../../lib/format.js'

function Box({ icon, title, ev, accent }) {
  const none = !ev || ev.hours == null
  const [d, h, m] = none ? ['—', '—', '—'] : [ev.days, ev.hours_component, ev.minutes]
  return (
    <div className="min-w-0 rounded-lg border border-line/80 bg-bg/60 p-3 text-center">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-mute">{icon} {title}</div>
      <div className={cx('num mt-1 text-2xl font-bold leading-tight', accent)}>
        {d}<span className="text-xs font-normal text-mute">d </span>{h}<span className="text-xs font-normal text-mute">h </span>{m}<span className="text-xs font-normal text-mute">m</span>
      </div>
      <div className="num mt-0.5 truncate text-[10px] text-mute">{none ? 'none before the window ends' : new Date(ev.event_time_utc).toISOString().slice(5, 16).replace('T', ' ') + ' UTC'}</div>
    </div>
  )
}

/** Card 3 - live countdowns: time to sunset (or sunrise when dark) and to Earthset (or Earthrise when blocked). */
export default function CountdownCards({ calc }) {
  const h = useTimeHours(100)
  const { sun, earth } = calc.countdown(h)
  return (
    <Card title="Live countdowns">
      <div className="grid grid-cols-2 gap-2">
        <Box icon="⏳" title={sun.currently_above_horizon ? 'Time to Sunset' : 'Time to Sunrise'} ev={sun} accent="text-solar" />
        <Box icon="📡" title={earth.currently_above_horizon ? 'Time to Earthset' : 'Time to Earthrise'} ev={earth} accent="text-earth" />
      </div>
    </Card>
  )
}
