import { Section, Badge, Stat } from '../ui/primitives.jsx'
import Sparkline from '../ui/Sparkline.jsx'
import { useTimeHours } from '../../lib/timeStore.js'
import { fmt } from '../../lib/format.js'

export const STATE_STYLE = {
  'Direct Sunlight': 'border-solar/60 bg-solar/15 text-solar',
  'Partial Shadow': 'border-solar/40 bg-[#92602b]/25 text-amber-300',
  'Total Darkness': 'border-line bg-panel2 text-mute',
}

/** Illumination state, Sun_Visible_Pct and live / peak Sun elevation (effective, with the tower horizon boost). */
export default function LightStatusCard({ calc }) {
  const h = useTimeHours()
  if (!calc) return null
  const now = calc.at(h)
  return (
    <Section title="Light level & illumination" icon="☀" accent="text-solar" right={<Badge className={STATE_STYLE[now.state]}>{now.state}</Badge>}>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Sun visible" value={fmt(calc.stats.sunVisPct, 1)} unit="%" className="text-solar" sub={`${calc.stats.sunHours} h above horizon`} />
        <Stat label="Sun elevation" value={`${now.sunEl >= 0 ? '+' : ''}${fmt(now.sunEl, 2)}`} unit="°" className="text-solar" sub="live (effective)" />
        <Stat label="Peak elevation" value={fmt(calc.stats.sunMax, 2)} unit="°" sub={`disc ${(now.disc * 100).toFixed(0)}% visible`} />
      </div>
      <div className="mt-2"><Sparkline data={calc.sunEff} color="#f59e0b" zero label="Sun elevation over the mission" /></div>
      <p className="mt-1 text-[10px] text-mute">Tower +{fmt(calc.boost, 3)}° horizon boost applied · solar disc radius 0.265°</p>
    </Section>
  )
}
