import { Card, Badge } from '../ui/primitives.jsx'
import { useTimeHours } from '../../lib/timeStore.js'
import { fmt, fmtW, cx } from '../../lib/format.js'
import InfoTip from '../ui/InfoTip.jsx'
import { GLOSSARY } from '../../lib/glossary.js'

const STATE_STYLE = {
  'Direct Sunlight': 'border-solar/60 bg-solar/15 text-solar',
  'Partial Shadow': 'border-solar/40 bg-[#92602b]/25 text-amber-300',
  'Total Darkness': 'border-line bg-panel2 text-mute',
}

function Tile({ label, badge, children }) {
  return (
    <div className="min-w-0 rounded-lg border border-line/80 bg-bg/50 p-2.5">
      <div className="mb-1 truncate text-[10px] font-semibold uppercase tracking-wider text-mute">{label}</div>
      {badge && <div className="mb-1.5">{badge}</div>}
      {children}
    </div>
  )
}
const Row = ({ k, v, className }) => <div className="flex items-baseline justify-between gap-2 text-[11px]"><span className="text-mute">{k}</span><span className={cx('num font-semibold text-ink', className)}>{v}</span></div>

/** Card 2 - core metrics in a clean 2x2 grid: terrain, sunlight, Earth comms, solar power (live at the timeline hour). */
export default function CoreMetrics({ result, calc }) {
  const h = useTimeHours(66)
  const t = result.terrain_topography_physics
  const now = calc.at(h)
  return (
    <Card title="Core metrics">
      <div className="grid grid-cols-2 gap-2">
        <Tile label="Terrain">
          <div className={cx('num text-xl font-bold', t.Slope_deg > 13.5 ? 'text-nogo' : 'text-ink')}>{fmt(t.Slope_deg, 2)}<span className="text-xs font-normal text-mute">° slope</span> <InfoTip text={GLOSSARY.slope} /></div>
          <Row k="Elevation" v={`${fmt(t.Elevation_m, 0)} m`} />
        </Tile>
        <Tile label="Sunlight" badge={<Badge className={STATE_STYLE[now.state]}>{now.state.replace('Direct ', '').replace('Total ', '')}</Badge>}>
          <div className="num text-xl font-bold text-solar">{fmt(calc.stats.sunVisPct, 1)}<span className="text-xs font-normal text-mute">% visible</span></div>
          <Row k={<>Sun angle <InfoTip text={GLOSSARY.sunElevation} /></>} v={`${now.sunEl >= 0 ? '+' : ''}${fmt(now.sunEl, 2)}°`} />
        </Tile>
        <Tile label="Earth comms" badge={<Badge className={now.connected ? 'border-earth/60 bg-earth/15 text-earth' : 'border-nogo/60 bg-nogo/15 text-nogo'}>{now.connected ? 'Connected' : 'Blocked'}</Badge>}>
          <div className="num text-xl font-bold text-earth">{fmt(calc.stats.earthVisPct, 1)}<span className="text-xs font-normal text-mute">% visible</span></div>
          <Row k={<>Earth angle <InfoTip text={GLOSSARY.earthElevation} /></>} v={`${now.earthEl >= 0 ? '+' : ''}${fmt(now.earthEl, 2)}°`} />
        </Tile>
        <Tile label="Solar power">
          <div className="num text-xl font-bold text-solar">{fmtW(now.power)}</div>
          <Row k="Mission energy" v={`${fmt(calc.stats.totalKwh, 0)} kWh`} />
        </Tile>
      </div>
    </Card>
  )
}
