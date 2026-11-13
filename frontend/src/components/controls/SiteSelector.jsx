import { useEffect, useState } from 'react'
import { SITES, siteById } from '../../lib/sites.js'
import { Label } from '../ui/primitives.jsx'
import { cx } from '../../lib/format.js'

function CoordInput({ label, value, min, max, unit, onCommit }) {
  const [text, setText] = useState(String(value))
  useEffect(() => { setText(Number.isFinite(value) ? String(Number(value.toFixed(4))) : '') }, [value])
  const n = parseFloat(text)
  const bad = text !== '' && !(n >= min && n <= max)
  const commit = () => { if (!bad && text !== '' && Number.isFinite(n) && n !== value) onCommit(n) }
  return (
    <label className="block">
      <Label right={<span className="num text-[10px]">{min}…{max}{unit}</span>}>{label}</Label>
      <input type="number" step="0.0001" min={min} max={max} value={text}
        onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === 'Enter' && commit()}
        className={cx('num w-full', bad && '!border-nogo')} aria-invalid={bad} />
    </label>
  )
}

/** Preset dropdown (100 sites) + manual Latitude / Longitude, bidirectionally synced with clicks on the 3-D Moon. */
export default function SiteSelector({ scenario, label, onSelect, onLatLon }) {
  const preset = scenario.siteId ? siteById(scenario.siteId) : null
  return (
    <div className="space-y-2.5">
      <label className="block">
        <Label right={<span className="num text-[10px] text-earth">{label}</span>}>Landing site</Label>
        <select value={scenario.siteId || 'custom'} onChange={(e) => e.target.value !== 'custom' && onSelect(e.target.value)} className="num w-full">
          {!scenario.siteId && <option value="custom">Custom coordinates</option>}
          {SITES.map((s) => (
            <option key={s.id} value={s.id}>{s.id} · {s.lat.toFixed(2)}°, {s.lon.toFixed(1)}°E · {s.slope.toFixed(1)}°</option>
          ))}
        </select>
      </label>
      <div className="grid grid-cols-2 gap-2">
        <CoordInput label="Latitude" value={scenario.lat} min={-90} max={-85} unit="°" onCommit={(v) => onLatLon(v, scenario.lon)} />
        <CoordInput label="Longitude" value={scenario.lon} min={0} max={360} unit="°E" onCommit={(v) => onLatLon(scenario.lat, v)} />
      </div>
      <p className="text-[10px] leading-snug text-mute">
        {preset ? <>Preset <span className="num text-ink">{preset.id}</span>: slope {preset.slope.toFixed(1)}°, elevation {preset.elev.toFixed(0)} m.</> : 'Custom point: terrain from the LOLA DEM (or nearest-site interpolation if unavailable).'} Click the Moon to set coordinates.
      </p>
    </div>
  )
}
