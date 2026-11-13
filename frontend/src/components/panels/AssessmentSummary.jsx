import { Card, Bar, Badge } from '../ui/primitives.jsx'
import { MODES } from '../../lib/physics.js'
import { STATUS, fmt, cx } from '../../lib/format.js'

const SEV = {
  CRITICAL: { dot: 'bg-nogo', text: 'text-nogo', box: 'border-nogo/40 bg-nogo/10' },
  WARNING: { dot: 'bg-solar', text: 'text-solar', box: 'border-solar/40 bg-solar/10' },
  INFO: { dot: 'bg-earth', text: 'text-earth', box: 'border-earth/30 bg-earth/5' },
}
const sevOf = (msg) => (/^CRITICAL/.test(msg) ? 'CRITICAL' : /^WARNING|^Tip-over|^Prolonged|^Comms blackout|^OOD/.test(msg) ? 'WARNING' : 'INFO')

/** 2-3 plain-language bullets explaining the verdict (the limiting subsystem first). */
function bullets(result) {
  const x = result.xai_and_hazard_alerts, p = result.primary_landing_decision
  const j = x.justifications || []
  const lim = x.explanation?.limiting_factor
  const out = [j[0]]
  out.push(lim === 'comms' ? j[2] : j[1]) // the subsystem costing the most points
  const sf = p.safety_factor
  if (sf?.layers_triggered?.length) out.push(`Safety factor: ${sf.layers_triggered.join(' + ').toLowerCase().replace(/_/g, ' ')} (operational slope limit ${sf.operational_slope_limit_deg}°).`)
  else if (p.guardrails?.triggered?.length) out.push(`Hard guardrail: ${p.guardrails.triggered.join(', ')}.`)
  else out.push(`Safety factor ${sf?.factor_of_safety ?? '1.11'}: all three layers clear.`)
  return out.filter(Boolean).slice(0, 3)
}

/** Card 4 - AI assessment: concise reasons + the most important active warning, with full diagnostics one click away. */
export default function AssessmentSummary({ result, mode }) {
  const x = result.xai_and_hazard_alerts, p = result.primary_landing_decision
  const st = STATUS[p.Safety_Class]
  const alerts = [...new Set(x.warnings || [])].filter((m) => !/^Offline mode/.test(m))
  const top = alerts.find((m) => sevOf(m) === 'CRITICAL') || alerts.find((m) => sevOf(m) === 'WARNING')
  const w = MODES[p.priority_mode || mode].w
  return (
    <Card title="AI assessment" right={<Badge className={cx(st.bg, st.border, st.color)}>{p.Safety_Class}</Badge>}>
      <ul className="space-y-1.5 text-[12px] leading-snug text-ink/90">
        {bullets(result).map((b, i) => <li key={i} className="flex gap-2"><span className="text-mute">▸</span><span>{b}</span></li>)}
      </ul>
      {top
        ? <div className={cx('mt-2.5 flex gap-2 rounded-md border px-2.5 py-2 text-[11.5px] leading-snug', SEV[sevOf(top)].box)}><i className={cx('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', SEV[sevOf(top)].dot)} /><span className={SEV[sevOf(top)].text}>{top}</span></div>
        : <div className="mt-2.5 rounded-md border border-go/30 bg-go/5 px-2.5 py-1.5 text-[11.5px] text-go">No active warnings</div>}

      <details className="group mt-2.5">
        <summary className="cursor-pointer select-none text-[11px] text-mute hover:text-ink">Full diagnostics</summary>
        <div className="mt-2.5 space-y-3">
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-mute">Subsystem score ({w.map((v) => Math.round(v * 100)).join(' / ')})</div>
            <Bar label="Terrain safety" value={x.component_scores.terrain} color="#10b981" valueLabel={`${fmt(x.component_scores.terrain, 0)}`} />
            <Bar label="Solar power" value={x.component_scores.solar} color="#f59e0b" valueLabel={`${fmt(x.component_scores.solar, 0)}`} />
            <Bar label="Earth comms" value={x.component_scores.comms} color="#38bdf8" valueLabel={`${fmt(x.component_scores.comms, 0)}`} />
          </div>
          {alerts.length > 0 && (
            <div className="space-y-1.5">
              {alerts.map((m, i) => { const s = SEV[sevOf(m)]; return <div key={i} className={cx('flex gap-2 rounded-md border px-2 py-1.5 text-[11px] leading-snug', s.box)}><i className={cx('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', s.dot)} /><span className={s.text}>{m}</span></div> })}
            </div>
          )}
          <ul className="space-y-1 text-[11px] leading-snug text-mute">{(x.justifications || []).map((j, i) => <li key={i}>› {j}</li>)}</ul>
        </div>
      </details>
    </Card>
  )
}
