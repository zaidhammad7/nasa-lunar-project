import { Section } from '../ui/primitives.jsx'
import { fmt, cx } from '../../lib/format.js'

const stamp = (s) => s.slice(5, 16).replace('T', ' ')

/** Top 3 landing windows (best simultaneous sunlight, DTE uptime and energy); click to jump the calendar + timeline. */
export default function SmartWindowList({ result, onJump }) {
  const wins = result?.top_3_landing_windows?.windows || []
  const cur = result?.scenario?.start_datetime_utc
  const L = result?.scenario?.duration_hours
  return (
    <Section title="Smart window finder" icon="🗓" accent="text-ink" defaultOpen>
      {wins.length === 0 && <div className="text-[11px] text-mute">No window of {L} h fits inside the baseline.</div>}
      <div className="space-y-1.5">
        {wins.map((w) => {
          const here = w.start_utc === cur
          return (
            <button key={w.rank} onClick={() => onJump(w)} className={cx('w-full rounded-lg border px-2.5 py-2 text-left transition-colors hover:border-earth/70 hover:bg-earth/5', here ? 'border-earth/60 bg-earth/10' : 'border-line/80 bg-bg/40')}>
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold"><span className="num mr-1.5 rounded bg-panel2 px-1.5 py-0.5 text-earth">#{w.rank}</span><span className="num">{stamp(w.start_utc)}</span> → <span className="num">{stamp(w.end_utc)}</span></span>
                {here && <span className="text-[9px] font-semibold uppercase text-earth">active</span>}
              </div>
              <div className="num mt-1 grid grid-cols-4 gap-1 text-[10.5px] text-mute">
                <span><span className="text-solar">{fmt(w.sunlight_hours, 0)}</span> h sun</span><span><span className="text-earth">{fmt(w.dte_uptime_pct, 0)}</span>% DTE</span>
                <span><span className="text-solar">{fmt(w.energy_kwh, 0)}</span> kWh</span><span>score {(w.objective * 100).toFixed(0)}</span>
              </div>
            </button>
          )
        })}
      </div>
      {wins.length > 0 && wins.length < 3 && <p className="mt-1.5 text-[10px] text-mute">Only {wins.length} non-overlapping {L} h window{wins.length > 1 ? 's' : ''} fit in the 60-day baseline; shorten the mission for more.</p>}
      <p className="mt-1.5 text-[10px] text-mute">Objective: 0.4 × energy + 0.3 × sunlight + 0.3 × DTE uptime (non-overlapping).</p>
    </Section>
  )
}
