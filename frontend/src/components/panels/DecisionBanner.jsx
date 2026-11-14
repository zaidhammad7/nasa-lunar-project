import { Card } from '../ui/primitives.jsx'
import { STATUS, fmt, cx } from '../../lib/format.js'
import InfoTip from '../ui/InfoTip.jsx'
import { GLOSSARY } from '../../lib/glossary.js'

/** Card 1 - Site Suitability Score: large score, GO / CONDITIONAL / Unsafe badge, model confidence, coordinates. */
export default function DecisionBanner({ result, liveScore, scn }) {
  const p = result.primary_landing_decision
  const st = STATUS[p.Safety_Class] || STATUS.Hazardous
  const ci = p.score_uncertainty_95ci
  const name = scn.siteId || 'Custom Selected Point'
  return (
    <Card className={cx('border-2', st.border)} accent="text-mute"
      title="Site Suitability Score"
      right={<span className="flex items-center gap-2">
        {result._pending && <span className="num animate-pulse text-[10px] text-solar" role="status">quick estimate · refining…</span>}
        {!result._pending && result._updating && <span className="num animate-pulse text-[10px] text-earth" role="status">updating…</span>}
        <InfoTip text={GLOSSARY.score} />
      </span>}>
      <div className="num mb-2 text-[12px] text-mute"><span className="text-ink">{name}</span> · {scn.lat.toFixed(4)}°, {scn.lon.toFixed(4)}°E</div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className={cx('num text-5xl font-bold leading-none', st.color)}>{fmt(liveScore, 1)}<span className="ml-1 text-lg font-normal text-mute">/100</span></div>
          <div className="num mt-1.5 text-[11px] text-mute">{ci ? <>±{fmt(ci.plus_minus, 1)} (95% CI) <InfoTip text={GLOSSARY.ci95} /></> : ''}</div>
        </div>
        <div className="text-right">
          <div className={cx('rounded-lg border px-3 py-1.5 text-[12px] font-bold tracking-wide', st.bg, st.border, st.color, p.Safety_Class === 'Optimal' && 'pulse-go')}>{st.label}{p.Safety_Class === 'Hazardous' && <InfoTip className="ml-1" text={GLOSSARY.unsafe} />}</div>
          <div className="num mt-1.5 text-[11px] text-mute">model confidence <span className="text-ink">{p.model_confidence_pct != null ? `${fmt(p.model_confidence_pct, 0)}%` : 'n/a'}</span></div>
        </div>
      </div>
    </Card>
  )
}
