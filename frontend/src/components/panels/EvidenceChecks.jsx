import { Card } from '../ui/primitives.jsx'
import { fmt, cx } from '../../lib/format.js'

const Check = ({ ok, label, detail }) => (
  <li className="flex items-start gap-2 text-[11.5px] leading-snug">
    <span className={cx('mt-px grid h-4 w-4 shrink-0 place-items-center rounded-full text-[10px] font-bold', ok ? 'bg-go/20 text-go' : 'bg-nogo/20 text-nogo')}>{ok ? '✓' : '✕'}</span>
    <span className="min-w-0"><span className="text-ink">{label}</span><span className="num block text-[10.5px] text-mute">{detail}</span></span>
  </li>
)

/** Evidence behind the verdict: the three independent safety layers with the measured numbers, plus data provenance. */
export default function EvidenceChecks({ result }) {
  const p = result.primary_landing_decision, t = result.terrain_topography_physics, sf = p.safety_factor
  if (!sf) return null
  const live = result._source === 'live'
  const th = result.solar_illumination_visibility?.terrain_horizon
  const slope = Number(t.Slope_deg), lim = sf.operational_slope_limit_deg
  const ci = p.score_uncertainty_95ci
  const rows = [
    { ok: slope <= lim, label: 'Slope within derated limit', detail: `${fmt(slope, 2)}° measured vs ${fmt(lim, 1)}° allowed (lander limit ${fmt(sf.mechanical_slope_limit_deg, 1)}° − ${sf.slope_safety_margin_deg}° margin)` },
    ...(sf.slope_plus_half_roughness_deg != null ? [{ ok: sf.slope_plus_half_roughness_deg <= lim, label: 'Slope + roughness allowance', detail: `${fmt(sf.slope_plus_half_roughness_deg, 2)}° effective vs ${fmt(lim, 1)}°` }] : []),
    ...(sf.conservative_score != null ? [{ ok: sf.conservative_score >= (sf.effective_acceptable_threshold ?? 0) - sf.score_buffer_pts, label: 'Worst-case score (95% CI lower bound)', detail: `${fmt(sf.conservative_score, 1)} vs threshold ${fmt(sf.effective_acceptable_threshold, 0)} (incl. +${sf.score_buffer_pts} pt buffer)` }] : ci ? [{ ok: true, label: 'Score confidence interval', detail: `${fmt(ci.lower, 1)} – ${fmt(ci.upper, 1)} (95%)` }] : []),
    ...(sf.p_hazardous != null ? [{ ok: sf.p_hazardous < sf.hazard_probability_threshold, label: 'Hazard probability', detail: `P(hazardous) ${fmt(sf.p_hazardous * 100, 0)}% vs ${fmt(sf.hazard_probability_threshold * 100, 0)}% limit` }] : []),
    ...(th?.terrain_shadowing ? [
      { ok: result.solar_illumination_visibility.Sun_Visible_Pct >= 25, label: 'Sunlight with real terrain shadowing', detail: `${fmt(result.solar_illumination_visibility.Sun_Visible_Pct, 1)}% of the time (NASA LOLA long-run average ${fmt(th.nasa_sun_visible_pct, 1)}%); crater-wall horizon ${fmt(th.sun_horizon_deg, 2)}°` },
      { ok: (result.earth_communication_status?.Earth_Visible_Pct ?? 0) >= 10, label: 'Earth in view with terrain shadowing', detail: `${fmt(result.earth_communication_status?.Earth_Visible_Pct, 1)}% of the time (NASA LOLA ${fmt(th.nasa_earth_visible_pct, 1)}%)` },
    ] : []),
    { ok: !p.ood_warning, label: 'Inside model training range', detail: p.ood_warning ? `out-of-distribution: ${(p.ood_features || []).join(', ')}` : 'features within the LRO-derived training data' },
  ]
  return (
    <Card title="Evidence">
      <ul className="space-y-2">{rows.map((r) => <Check key={r.label} {...r} />)}</ul>
      <div className="num mt-3 border-t border-line pt-2 text-[10px] leading-relaxed text-mute">
        Data: {live ? `live backend · NASA LRO LOLA terrain (DEM) · JPL Horizons Sun/Earth ephemeris${th?.terrain_shadowing ? ' · NASA LOLA terrain-shadowed illumination' : ' · smooth horizon (no terrain shadowing)'}` : 'offline estimate (backend unreachable): sunlight interpolated from nearby NASA-corrected sites — lower confidence'}.
        Moon imagery: NASA CGI Moon Kit (LROC / LOLA).
      </div>
    </Card>
  )
}
