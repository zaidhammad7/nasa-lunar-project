import { useEffect } from 'react'
import SiteSelector from '../controls/SiteSelector.jsx'
import { fmt, sign, cx } from '../../lib/format.js'

const ROWS = [
  { k: 'delta_suitability_score', label: 'Suitability score', unit: '', better: 1, get: (e) => e.primary_landing_decision.Suitability_Score, d: 1 },
  { k: 'delta_slope_deg', label: 'Terrain slope', unit: '°', better: -1, get: (e) => e.terrain_topography_physics.Slope_deg, d: 2 },
  { k: 'delta_sunlight_hours', label: 'Sunlight hours', unit: ' h', better: 1, get: (e) => e.solar_illumination_visibility.sunlight_hours, d: 0 },
  { k: 'delta_power_watts', label: 'Mean power', unit: ' W', better: 1, get: (e) => e.power_generation.average_power_watts, d: 0 },
  { k: 'delta_energy_kwh', label: 'Mission energy', unit: ' kWh', better: 1, get: (e) => e.power_generation.total_accumulated_energy_kwh, d: 0 },
  { k: 'delta_comms_uptime_pct', label: 'Comms uptime', unit: '%', better: 1, get: (e) => e.earth_communication_status.Earth_Visible_Pct, d: 1 },
]
const label = (e) => e.scenario.site_id || `${e.scenario.lat_deg.toFixed(2)}°, ${e.scenario.lon_deg_east.toFixed(1)}°E`

/** Site A vs. Site B in a clean modal: pick Site B, read the +/- trade-offs (B − A). Site B shares Site A's date and hardware. */
export default function ComparisonModal({ results, scnB, onSelectB, onLatLonB, onClose }) {
  useEffect(() => { const k = (e) => e.key === 'Escape' && onClose(); document.addEventListener('keydown', k); return () => document.removeEventListener('keydown', k) }, [onClose])
  const { A, B, deltas } = results
  const ready = A && B && deltas
  const wins = ready ? ROWS.filter((r) => deltas[r.k] * r.better > 0).length : 0
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="dialog" aria-modal="true" aria-label="Compare two sites">
      <div className="glass max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-line shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em]">Compare Site A vs Site B</h2>
          <button onClick={onClose} className="rounded px-2 py-1 text-mute hover:bg-panel2 hover:text-ink" aria-label="Close">✕</button>
        </div>
        <div className="grid gap-5 p-5 md:grid-cols-[260px_1fr]">
          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-scenb">Site B</div>
            <SiteSelector scenario={scnB} onSelect={onSelectB} onLatLon={onLatLonB} tag="B" />
            <p className="mt-3 text-[10.5px] leading-snug text-mute">Site A is your current selection. Both sites use the same start date, duration and hardware.</p>
          </div>
          <div className="min-w-0">
            {!ready ? <div className="grid h-40 place-items-center text-[12px] text-mute">Evaluating both sites…</div> : (
              <>
                <table className="num w-full text-[12px]">
                  <thead className="text-[10px] uppercase text-mute">
                    <tr><th className="text-left">Metric</th><th style={{ color: '#38bdf8' }}>A · {label(A)}</th><th style={{ color: '#a78bfa' }}>B · {label(B)}</th><th>Δ (B−A)</th></tr>
                  </thead>
                  <tbody>
                    {ROWS.map((r) => {
                      const dv = deltas[r.k], good = dv * r.better > 0, bad = dv * r.better < 0
                      return (
                        <tr key={r.k} className="border-t border-line/60 text-center">
                          <td className="py-2 text-left text-mute">{r.label}</td><td>{fmt(r.get(A), r.d)}{r.unit}</td><td>{fmt(r.get(B), r.d)}{r.unit}</td>
                          <td className={cx('font-semibold', good && 'text-go', bad && 'text-nogo', !good && !bad && 'text-mute')}>{good ? '▲' : bad ? '▼' : '='} {sign(dv, r.d)}{r.unit}</td>
                        </tr>
                      )
                    })}
                    <tr className="border-t border-line/60 text-center"><td className="py-2 text-left text-mute">Verdict</td><td className="text-[10.5px]">{A.primary_landing_decision.mission_status_label}</td><td className="text-[10.5px]">{B.primary_landing_decision.mission_status_label}</td><td /></tr>
                  </tbody>
                </table>
                <p className="mt-3 text-[11px] text-mute">Site B is better on <span className="num text-ink">{wins}/{ROWS.length}</span> metrics. Green = favourable to B (a lower slope is favourable).</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
