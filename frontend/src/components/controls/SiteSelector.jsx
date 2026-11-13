import { useEffect, useState } from 'react'
import { SITES, siteById } from '../../lib/sites.js'
import { Label } from '../ui/primitives.jsx'
import { cx } from '../../lib/format.js'

const fmtCoord = (v) => (Number.isFinite(v) ? String(Number(v.toFixed(4))) : '')

/**
 * Location: optional preset dropdown + manual Latitude / Longitude. Clicking the 3-D Moon fills the boxes with the exact
 * clicked point; typing any coordinates and pressing Enter / Apply evaluates exactly that point (never snapped to a preset).
 */
export default function SiteSelector({ scenario, onSelect, onLatLon, showPresets, onTogglePresets, tag }) {
  const [lat, setLat] = useState(fmtCoord(scenario.lat))
  const [lon, setLon] = useState(fmtCoord(scenario.lon))
  useEffect(() => { setLat(fmtCoord(scenario.lat)); setLon(fmtCoord(scenario.lon)) }, [scenario.lat, scenario.lon])
  const la = parseFloat(lat), lo = parseFloat(lon)
  const badLat = lat !== '' && !(la >= -90 && la <= -85), badLon = lon !== '' && !(lo >= 0 && lo <= 360)
  const dirty = Number.isFinite(la) && Number.isFinite(lo) && (la !== Number(scenario.lat.toFixed(4)) || lo !== Number(scenario.lon.toFixed(4)))
  const apply = () => { if (!badLat && !badLon && Number.isFinite(la) && Number.isFinite(lo)) onLatLon(la, lo) }
  const preset = scenario.siteId ? siteById(scenario.siteId) : null
  const key = (e) => e.key === 'Enter' && apply()

  return (
    <div className="space-y-3">
      <label className="block">
        <Label right={tag && <span className="num text-[10px] text-earth">{tag}</span>}>Preset site (optional)</Label>
        <select value={scenario.siteId || 'custom'} onChange={(e) => e.target.value !== 'custom' && onSelect(e.target.value)} className="num w-full">
          {!scenario.siteId && <option value="custom">Custom Selected Point</option>}
          {SITES.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.lat.toFixed(2)}°, {s.lon.toFixed(1)}°E</option>)}
        </select>
      </label>

      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <Label right={<span className="num text-[10px]">−90…−85°</span>}>Latitude</Label>
          <input type="number" step="0.0001" value={lat} onChange={(e) => setLat(e.target.value)} onKeyDown={key} aria-invalid={badLat} className={cx('num w-full', badLat && '!border-nogo')} />
        </label>
        <label className="block">
          <Label right={<span className="num text-[10px]">0…360°E</span>}>Longitude</Label>
          <input type="number" step="0.0001" value={lon} onChange={(e) => setLon(e.target.value)} onKeyDown={key} aria-invalid={badLon} className={cx('num w-full', badLon && '!border-nogo')} />
        </label>
      </div>
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-[10.5px] text-mute">{preset ? <>Preset <span className="num text-ink">{preset.id}</span></> : <span className="text-earth">Custom Selected Point</span>} · or click the Moon</p>
        <button onClick={apply} disabled={!dirty || badLat || badLon}
          className="shrink-0 rounded-md border border-earth/60 bg-earth/15 px-3 py-1 text-[11px] font-semibold text-earth transition-colors enabled:hover:bg-earth/25 disabled:opacity-40">Apply</button>
      </div>

      {onTogglePresets && (
        <label className="flex cursor-pointer items-center gap-2 border-t border-line/70 pt-2.5 text-[11.5px] text-mute select-none">
          <input type="checkbox" checked={showPresets} onChange={onTogglePresets} className="h-3.5 w-3.5 accent-sky-400" />
          Show 100 preset pins on the Moon
        </label>
      )}
    </div>
  )
}
