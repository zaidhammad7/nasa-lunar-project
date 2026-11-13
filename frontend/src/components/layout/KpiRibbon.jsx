import { Badge } from '../ui/primitives.jsx'
import { useTimeHours } from '../../lib/timeStore.js'
import { STATUS, fmt, fmtW, cx } from '../../lib/format.js'
import { STATE_STYLE } from '../telemetry/LightStatusCard.jsx'
import { Countdown, countdownTitles } from '../telemetry/CountdownTimers.jsx'

function Card({ label, accent, children, right, className }) {
  return (
    <div className={cx('glass relative min-w-0 overflow-hidden rounded-xl border border-line px-2.5 pb-2 pt-2', className)}>
      <i className="absolute inset-x-0 top-0 h-0.5" style={{ background: accent }} />
      <div className="mb-1 truncate text-[9.5px] font-semibold uppercase tracking-[0.12em] text-mute">{label}</div>
      <div className="mb-1 flex min-h-[18px] items-center">{right}</div>
      {children}
    </div>
  )
}
const Big = ({ children, unit, className }) => <div className={cx('num text-[24px] font-semibold leading-none', className)}>{children}{unit && <span className="ml-0.5 text-sm font-normal text-mute">{unit}</span>}</div>
const Sub = ({ children }) => <div className="num mt-1.5 truncate text-[10.5px] text-mute">{children}</div>

/** Top executive strip: 6 live mission KPIs at a glance. */
export default function KpiRibbon({ result, liveScore, calc }) {
  const h = useTimeHours(66)
  const p = result?.primary_landing_decision
  const t = result?.terrain_topography_physics
  if (!p || !t || !calc) {
    return <div className="grid grid-cols-6 gap-2 p-2.5">{Array.from({ length: 6 }, (_, i) => <div key={i} className="glass h-[112px] animate-pulse rounded-xl border border-line" />)}</div>
  }
  const now = calc.at(h)
  const cd = calc.countdown(h)
  const ct = countdownTitles(cd.sun, cd.earth)
  const st = STATUS[p.Safety_Class] || STATUS.Hazardous
  const ci = p.score_uncertainty_95ci
  const sf = p.safety_factor
  return (
    <div className="grid grid-cols-2 gap-2 p-2.5 md:grid-cols-3 wide:grid-cols-6">
      <Card label="Landing decision" accent={st.hex} right={<Badge className={cx(st.bg, st.border, st.color, p.Safety_Class === 'Optimal' && 'pulse-go')}>{st.label}</Badge>}>
        <Big className={st.color}>{fmt(liveScore, 1)}<span className="ml-0.5 text-sm font-normal text-mute">/100</span></Big>
        <Sub>{ci ? `±${fmt(ci.plus_minus, 1)} (95% CI)` : ''} · conf {p.model_confidence_pct != null ? `${fmt(p.model_confidence_pct, 0)}%` : 'n/a'}</Sub>
        <div className="num mt-0.5 truncate text-[10.5px]"><span className={sf?.layers_triggered?.length ? 'text-nogo' : 'text-go'}>● SF {sf?.factor_of_safety ?? '1.11'}</span><span className="text-mute"> · {sf?.layers_triggered?.length ? sf.layers_triggered.join('+') : '3 layers clear'}</span></div>
      </Card>

      <Card label="Terrain & slope" accent="#10b981">
        <Big className={t.Slope_deg > 13.5 ? 'text-nogo' : 'text-ink'} unit="°">{fmt(t.Slope_deg, 2)}</Big>
        <Sub>elev <span className="text-ink">{fmt(t.Elevation_m, 1)} m</span> · rough <span className="text-ink">{t.Roughness_m != null ? `${fmt(t.Roughness_m, 2)} m` : '—'}</span></Sub>
        <Sub>polar-corrected · cutoff 13.5°</Sub>
      </Card>

      <Card label="Solar illumination" accent="#f59e0b" right={<Badge className={STATE_STYLE[now.state]}>{now.state.replace('Direct ', '').replace('Total ', '')}</Badge>}>
        <Big className="text-solar" unit="%">{fmt(calc.stats.sunVisPct, 1)}</Big>
        <Sub>el <span className="text-ink">{now.sunEl >= 0 ? '+' : ''}{fmt(now.sunEl, 2)}°</span> · peak <span className="text-ink">{fmt(calc.stats.sunMax, 2)}°</span></Sub>
      </Card>

      <Card label="Earth DTE comms" accent="#38bdf8" right={<Badge className={now.connected ? 'border-earth/60 bg-earth/15 text-earth' : 'border-nogo/60 bg-nogo/15 text-nogo'}>{now.connected ? 'Connected' : 'Blocked'}</Badge>}>
        <Big className="text-earth" unit="%">{fmt(calc.stats.earthVisPct, 1)}</Big>
        <Sub>el <span className="text-ink">{now.earthEl >= 0 ? '+' : ''}{fmt(now.earthEl, 2)}°</span> · peak <span className="text-ink">{fmt(calc.stats.earthMax, 2)}°</span></Sub>
      </Card>

      <Card label="Power & energy" accent="#f59e0b">
        <Big className="text-solar">{fmtW(now.power)}</Big>
        <Sub>energy <span className="text-ink">{fmt(now.cumKwh, 1)} kWh</span> / {fmt(calc.stats.totalKwh, 0)} kWh</Sub>
      </Card>

      <Card label="Countdowns" accent="#94a3b8" className="md:col-span-1">
        <div className="grid gap-1">
          <Countdown title={ct.sun} ev={cd.sun} accent="text-solar" compact />
          <Countdown title={ct.earth} ev={cd.earth} accent="text-earth" compact />
        </div>
      </Card>
    </div>
  )
}
