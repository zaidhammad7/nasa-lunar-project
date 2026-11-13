import { Card } from '../ui/primitives.jsx'
import VehicleFilters from '../controls/VehicleFilters.jsx'
import { compass, MODES } from '../../lib/physics.js'
import { STATUS } from '../../lib/format.js'

/** Top 5 safe alternatives for the active priority mode + vehicle filters; clicking a row flies the camera there. */
export default function BackupSites({ ranking, mode, scn, onSelect, onPatch }) {
  const rows = ranking?.top5 || []
  return (
    <Card title="Top 5 safe alternatives" icon="📍" accent="text-go">
      <div className="num mb-2 text-[10px] text-mute">ranked by {MODES[mode].label} · {ranking?.nPassing} of 100 sites pass · slope ≤ {ranking?.effectiveMaxSlope.toFixed(1)}° (safety-derated)</div>
      {rows.length === 0 ? <div className="rounded-md border border-line p-3 text-center text-[11px] text-mute">No site satisfies all filters. Relax the vehicle constraints below.</div> : (
        <div className="overflow-hidden rounded-lg border border-line/80">
          <table className="num w-full text-[11px]">
            <thead className="bg-panel2/70 text-[9.5px] uppercase text-mute"><tr><th className="px-1.5 py-1 text-left">#</th><th className="text-left">Site</th><th>Score</th><th>Slope</th><th>km</th><th>Bearing</th></tr></thead>
            <tbody>
              {rows.map((s, i) => (
                <tr key={s.id} onClick={() => onSelect(s.id)} className="cursor-pointer border-t border-line/60 text-center transition-colors hover:bg-earth/10" title="Fly to this site">
                  <td className="px-1.5 py-1.5 text-left text-mute">{i + 1}</td>
                  <td className="text-left"><i className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: STATUS[s.displayClass].hex }} />{s.id.replace('Auto_', '')}</td>
                  <td className="font-semibold text-ink">{s.modeScore.toFixed(1)}</td><td>{s.slope.toFixed(1)}°</td><td>{s.distanceKm.toFixed(0)}</td><td>{s.bearing.toFixed(0)}° {compass(s.bearing)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className="mt-3">
        <summary className="cursor-pointer select-none text-[11px] text-mute hover:text-ink">Vehicle constraints (max slope · min Sun · min Earth)</summary>
        <div className="mt-3"><VehicleFilters scenario={scn} onPatch={onPatch} /></div>
      </details>
    </Card>
  )
}
