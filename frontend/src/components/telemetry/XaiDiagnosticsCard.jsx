import { Section, Bar, Badge } from '../ui/primitives.jsx'
import { compass, MODES } from '../../lib/physics.js'
import { STATUS, fmt, cx } from '../../lib/format.js'

const SEV = {
  CRITICAL: { dot: 'bg-nogo', text: 'text-nogo', box: 'border-nogo/40 bg-nogo/10' },
  WARNING: { dot: 'bg-solar', text: 'text-solar', box: 'border-solar/40 bg-solar/10' },
  INFO: { dot: 'bg-earth', text: 'text-earth', box: 'border-earth/30 bg-earth/5' },
}
const sevOf = (msg) => (/^CRITICAL/.test(msg) ? 'CRITICAL' : /^WARNING|^Tip-over|^Prolonged|^Comms blackout|^OOD/.test(msg) ? 'WARNING' : 'INFO')

/** Explainable AI: sub-score breakdown, safety-factor status, engineering justifications and automated hazard alerts. */
export function XaiPanel({ result, mode }) {
  const x = result?.xai_and_hazard_alerts
  const p = result?.primary_landing_decision
  if (!x || !p) return null
  const w = MODES[p.priority_mode || mode].w
  const expl = x.explanation
  const sens = Object.entries(expl?.feature_sensitivity_pts || {}).slice(0, 4)
  const sf = p.safety_factor
  const alerts = [...new Set(x.warnings || [])].filter((m) => !/^Offline mode/.test(m))
  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wider text-mute">Subsystem breakdown (weights {w.map((v) => Math.round(v * 100)).join(' / ')})</div>
        <Bar label={`Terrain safety · ${Math.round(w[0] * 100)}%`} value={x.component_scores.terrain} color="#10b981" valueLabel={`${fmt(x.component_scores.terrain, 0)} → ${fmt(w[0] * x.component_scores.terrain, 1)} pts`} />
        <Bar label={`Solar power · ${Math.round(w[1] * 100)}%`} value={x.component_scores.solar} color="#f59e0b" valueLabel={`${fmt(x.component_scores.solar, 0)} → ${fmt(w[1] * x.component_scores.solar, 1)} pts`} />
        <Bar label={`Earth comms · ${Math.round(w[2] * 100)}%`} value={x.component_scores.comms} color="#38bdf8" valueLabel={`${fmt(x.component_scores.comms, 0)} → ${fmt(w[2] * x.component_scores.comms, 1)} pts`} />
        {expl?.limiting_factor && <div className="text-[10px] text-mute">Largest loss: <span className="text-ink">{expl.limiting_factor}</span> (−{fmt(expl.points_lost_by_component[expl.limiting_factor], 1)} pts)</div>}
      </div>

      {sf && (
        <div className={cx('rounded-lg border px-2.5 py-2 text-[11px]', sf.layers_triggered?.length ? 'border-nogo/40 bg-nogo/10' : 'border-go/30 bg-go/5')}>
          <div className="flex items-center justify-between">
            <span className="font-semibold">3-layer safety factor <span className="num text-mute">FS {sf.factor_of_safety ?? '—'}</span></span>
            <Badge className={sf.layers_triggered?.length ? 'border-nogo/50 text-nogo' : 'border-go/50 text-go'}>{sf.layers_triggered?.length ? `${sf.layers_triggered.length} triggered` : 'clear'}</Badge>
          </div>
          <div className="num mt-1 text-[10.5px] text-mute">slope cutoff {sf.operational_slope_limit_deg}° (limit {sf.mechanical_slope_limit_deg}° − {sf.slope_safety_margin_deg}°) · score buffer ≥ 48 · P(Haz) &lt; 0.28</div>
          {sf.layers_triggered?.length > 0 && <div className="num mt-1 text-[10.5px] text-nogo">{sf.layers_triggered.join(' · ')}</div>}
        </div>
      )}

      {alerts.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wider text-mute">Hazard alerts</div>
          {alerts.map((m, i) => { const s = SEV[sevOf(m)]; return (
            <div key={i} className={cx('flex gap-2 rounded-md border px-2 py-1.5 text-[11px] leading-snug', s.box)}><i className={cx('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', s.dot)} /><span className={s.text}>{m}</span></div>
          ) })}
        </div>
      )}
      {x.ood_warning && !alerts.some((m) => /^OOD/.test(m)) && <div className="rounded-md border border-solar/40 bg-solar/10 px-2 py-1.5 text-[11px] text-solar">OOD: {x.ood_features.join(', ')} outside the training range - treat the ML score with caution.</div>}

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wider text-mute">Engineering justification</div>
        <ul className="space-y-1 text-[11px] leading-snug text-ink/90">{(x.justifications || []).slice(0, 6).map((j, i) => <li key={i} className="flex gap-1.5"><span className="text-mute">›</span><span>{j}</span></li>)}</ul>
      </div>

      {sens.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-mute">Feature sensitivity (pts vs dataset median)</div>
          {sens.map(([k, v]) => <Bar key={k} label={k} value={Math.abs(v)} max={Math.max(...sens.map(([, x]) => Math.abs(x)), 1)} color={v >= 0 ? '#10b981' : '#f43f5e'} valueLabel={`${v >= 0 ? '+' : ''}${v.toFixed(1)}`} />)}
        </div>
      )}
    </div>
  )
}

/** Top 5 safe alternatives under the active mode + vehicle filters; clicking a row flies the 3-D camera there. */
export function TopSitesTable({ ranking, onSelect, mode }) {
  const rows = ranking?.top5 || []
  return (
    <div>
      <div className="num mb-1.5 text-[10px] text-mute">{ranking?.nPassing} sites pass · slope ≤ {ranking?.effectiveMaxSlope.toFixed(1)}° (safety-derated) · ranked by {MODES[mode].label}</div>
      {rows.length === 0 ? <div className="rounded-md border border-line p-3 text-center text-[11px] text-mute">No site satisfies all filters. Relax the vehicle constraints.</div> : (
        <div className="overflow-hidden rounded-lg border border-line/80">
          <table className="num w-full text-[11px]">
            <thead className="bg-panel2/70 text-[9.5px] uppercase text-mute"><tr><th className="px-1.5 py-1 text-left">#</th><th className="text-left">Site</th><th>Score</th><th>Slope</th><th>Sun%</th><th>Earth%</th><th>km</th><th>Brg</th></tr></thead>
            <tbody>
              {rows.map((s, i) => (
                <tr key={s.id} onClick={() => onSelect(s.id)} className="cursor-pointer border-t border-line/60 text-center transition-colors hover:bg-earth/10" title="Fly to this site">
                  <td className="px-1.5 py-1.5 text-left text-mute">{i + 1}</td>
                  <td className="text-left"><i className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: STATUS[s.displayClass].hex }} />{s.id.replace('Auto_', '')}</td>
                  <td className="font-semibold text-ink">{s.modeScore.toFixed(1)}</td><td>{s.slope.toFixed(1)}°</td><td className="text-solar">{s.sun.toFixed(0)}</td><td className="text-earth">{s.earth.toFixed(0)}</td>
                  <td>{s.distanceKm.toFixed(0)}</td><td>{s.bearing.toFixed(0)}°{compass(s.bearing)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function XaiDiagnosticsCard({ result, mode, ranking, onSelectSite }) {
  return (
    <>
      <Section title="Explainable AI & hazard alerts" icon="🧠" accent="text-ink"><XaiPanel result={result} mode={mode} /></Section>
      <Section title="Top 5 alternative safe sites" icon="📍" accent="text-go"><TopSitesTable ranking={ranking} onSelect={onSelectSite} mode={mode} /></Section>
    </>
  )
}
