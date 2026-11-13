import { useState } from 'react'
import { fmt, sign, cx } from '../../lib/format.js'

const ROWS = [
  { k: 'delta_suitability_score', label: 'Suitability score', unit: '', better: 1, get: (e) => e.primary_landing_decision.Suitability_Score, d: 1 },
  { k: 'delta_slope_deg', label: 'Terrain slope', unit: '°', better: -1, get: (e) => e.terrain_topography_physics.Slope_deg, d: 2 },
  { k: 'delta_sunlight_hours', label: 'Sunlight hours', unit: ' h', better: 1, get: (e) => e.solar_illumination_visibility.sunlight_hours, d: 0 },
  { k: 'delta_power_watts', label: 'Mean power', unit: ' W', better: 1, get: (e) => e.power_generation.average_power_watts, d: 0 },
  { k: 'delta_energy_kwh', label: 'Mission energy', unit: ' kWh', better: 1, get: (e) => e.power_generation.total_accumulated_energy_kwh, d: 0 },
  { k: 'delta_comms_uptime_pct', label: 'Comms uptime', unit: '%', better: 1, get: (e) => e.earth_communication_status.Earth_Visible_Pct, d: 1 },
]

/** Site A vs. Site B: both KPI values and the exact +/- trade-off deltas (B − A) from POST /api/compare. */
export default function ComparisonModal({ results, scn, onClose }) {
  const [min, setMin] = useState(false)
  const { A, B, deltas } = results
  if (!A || !B || !deltas) return null
  const name = (e, s) => e.scenario.site_id || `${e.scenario.lat_deg.toFixed(2)}°, ${e.scenario.lon_deg_east.toFixed(1)}°E`
  const wins = ROWS.filter((r) => deltas[r.k] * r.better > 0).length
  return (
    <div className="glass absolute right-3 top-3 z-20 w-[430px] max-w-[calc(100%-1.5rem)] rounded-xl border border-line shadow-2xl">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em]">Site A vs. Site B</div>
        <div className="flex items-center gap-2">
          <span className="num rounded border border-line px-1.5 py-0.5 text-[10px] text-mute">B better on {wins}/{ROWS.length}</span>
          <button onClick={() => setMin((m) => !m)} className="text-mute hover:text-ink" aria-label={min ? 'Expand' : 'Collapse'}>{min ? '▢' : '▁'}</button>
          <button onClick={onClose} className="text-mute hover:text-ink" aria-label="Close comparison">✕</button>
        </div>
      </div>
      {!min && (
        <div className="p-3">
          <table className="num w-full text-[11.5px]">
            <thead className="text-[10px] uppercase text-mute">
              <tr><th className="text-left">Metric</th><th className="text-cyan-300" style={{ color: '#38bdf8' }}>A · {name(A)}</th><th style={{ color: '#a78bfa' }}>B · {name(B)}</th><th>Δ (B−A)</th></tr>
            </thead>
            <tbody>
              {ROWS.map((r) => {
                const dv = deltas[r.k], good = dv * r.better > 0, bad = dv * r.better < 0
                return (
                  <tr key={r.k} className="border-t border-line/60 text-center">
                    <td className="py-1.5 text-left text-mute">{r.label}</td>
                    <td>{fmt(r.get(A), r.d)}{r.unit}</td><td>{fmt(r.get(B), r.d)}{r.unit}</td>
                    <td className={cx('font-semibold', good && 'text-go', bad && 'text-nogo', !good && !bad && 'text-mute')}>{good ? '▲' : bad ? '▼' : '='} {sign(dv, r.d)}{r.unit}</td>
                  </tr>
                )
              })}
              <tr className="border-t border-line/60 text-center">
                <td className="py-1.5 text-left text-mute">Verdict</td>
                <td className="text-[10px]">{A.primary_landing_decision.mission_status_label}</td><td className="text-[10px]">{B.primary_landing_decision.mission_status_label}</td><td />
              </tr>
            </tbody>
          </table>
          <p className="mt-2 text-[10px] text-mute">Green = favourable to B (lower slope is favourable). Each scenario keeps its own date and hardware; switch the Location tabs to edit B.</p>
        </div>
      )}
    </div>
  )
}
