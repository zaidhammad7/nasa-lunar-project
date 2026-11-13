import { Section, Badge, Stat } from '../ui/primitives.jsx'
import Sparkline from '../ui/Sparkline.jsx'
import { useTimeHours } from '../../lib/timeStore.js'
import { fmt } from '../../lib/format.js'

/** Earth direct-to-Earth link: Connected / Blocked badge, Earth_Visible_Pct and live / peak Earth elevation. */
export default function CommsStatusCard({ calc }) {
  const h = useTimeHours()
  if (!calc) return null
  const now = calc.at(h)
  return (
    <Section title="Earth connection (DTE)" icon="📡" accent="text-earth"
      right={<Badge className={now.connected ? 'border-earth/60 bg-earth/15 text-earth' : 'border-nogo/60 bg-nogo/15 text-nogo'}>{now.connected ? 'Connected' : 'Blocked'}</Badge>}>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Earth visible" value={fmt(calc.stats.earthVisPct, 1)} unit="%" className="text-earth" />
        <Stat label="Earth elevation" value={`${now.earthEl >= 0 ? '+' : ''}${fmt(now.earthEl, 2)}`} unit="°" className={now.connected ? 'text-earth' : 'text-nogo'} sub="live (effective)" />
        <Stat label="Peak elevation" value={fmt(calc.stats.earthMax, 2)} unit="°" />
      </div>
      <p className={`num mt-1.5 text-[11px] ${now.connected ? 'text-earth' : 'text-nogo'}`}>{now.dte}</p>
      <div className="mt-1"><Sparkline data={calc.earthEff} color="#38bdf8" zero label="Earth elevation over the mission" /></div>
    </Section>
  )
}
