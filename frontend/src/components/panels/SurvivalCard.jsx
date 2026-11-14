import { useMemo, useState } from 'react'
import { Card } from '../ui/primitives.jsx'
import InfoTip from '../ui/InfoTip.jsx'
import { GLOSSARY } from '../../lib/glossary.js'
import { simulateBattery, requiredCapacityKwh, longestDarkHours } from '../../lib/survival.js'
import { useTimeHours } from '../../lib/timeStore.js'
import { fmt, cx } from '../../lib/format.js'

// Chart colours validated with the dataviz skill's validator (scripts/validate_palette.js) against this app's dark chart surface
// #0b1120: series slot 1 blue + status "critical" red -> lightness band, chroma floor, CVD dE 25.7, normal-vision dE 31.9 and
// contrast >= 3:1 all PASS. Status colours are reserved (good / warning / critical) and always ship with an icon and a word.
const SERIES = '#3987e5', CRITICAL = '#d03b3b', NEUTRAL = '#94a3b8', GRID = '#334155', NIGHT = '#1e293b' // night band: a neutral lighter than the chart surface so it reads as shading
const STATUS_CUE = {
  good: { icon: '✓', color: '#0ca30c' }, warning: { icon: '!', color: '#fab219' }, critical: { icon: '✕', color: CRITICAL },
}
const W = 300, H = 80, PAD_L = 22 // chart viewBox; left gutter for the % axis labels

const Num = ({ label, unit, value, onChange, min, max, step }) => (
  <label className="block min-w-0">
    <span className="mb-1 block text-[10.5px] text-mute">{label} ({unit})</span>
    <input type="number" className="num w-full" value={value} min={min} max={max} step={step} aria-label={`${label} in ${unit}`}
      onChange={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v) && v >= min && v <= max) onChange(v) }} />
  </label>
)

/** One bold metric tile: big value in text ink (never in a data colour), unit, label, optional status cue (icon + word). */
const Stat = ({ label, value, unit, status, statusText, sub }) => (
  <div className="min-w-0 rounded-lg border border-line/80 bg-bg/50 px-2.5 py-2">
    <div className="truncate text-[9.5px] font-semibold uppercase tracking-wider text-mute">{label}</div>
    <div className="num mt-0.5 text-[22px] font-bold leading-none text-ink">{value}<span className="ml-0.5 text-[11px] font-normal text-mute">{unit}</span></div>
    {status && <div className="mt-1 truncate text-[10px] font-semibold" style={{ color: STATUS_CUE[status].color }}>{STATUS_CUE[status].icon} {statusText}</div>}
    {sub && <div className="num mt-0.5 truncate text-[10px] text-mute">{sub}</div>}
  </div>
)

/**
 * Battery charge (%) hour by hour - a single-series area chart (the title names it, so no legend box). Hours with the Sun hidden
 * are shaded, hours without power are marked in the reserved critical red (labelled in the key), a neutral dashed cursor follows
 * the mission clock, and hovering shows the exact hour, charge and solar power. A per-day table gives the same data as text.
 */
function ChargeChart({ soc, power, startMs }) {
  const now = useTimeHours(100)
  const [hover, setHover] = useState(null)
  const n = soc.length
  const x = (i) => PAD_L + (i / Math.max(n - 1, 1)) * (W - PAD_L)
  const y = (p) => H - 4 - (p / 100) * (H - 10)
  const runs = (pred, minLen = 1) => {
    const r = []
    let s = -1
    for (let i = 0; i <= n; i++) {
      const on = i < n && pred(i)
      if (on && s < 0) s = i
      if (!on && s >= 0) { if (i - s >= minLen) r.push([s, i]); s = -1 }
    }
    return r
  }
  /* eslint-disable react-hooks/exhaustive-deps */
  const line = useMemo(() => { let d = ''; for (let i = 0; i < n; i += Math.max(1, Math.floor(n / 300))) d += `${d ? 'L' : 'M'}${x(i).toFixed(1)},${y(soc[i]).toFixed(1)}`; return d }, [soc])
  const empty = useMemo(() => runs((i) => soc[i] <= 0), [soc])
  const dark = useMemo(() => runs((i) => power[i] <= 0, 6), [power])
  /* eslint-enable react-hooks/exhaustive-deps */
  const days = useMemo(() => Array.from({ length: Math.ceil(n / 24) }, (_, d) => {
    const s = Array.from(soc.slice(d * 24, d * 24 + 24))
    return { day: d + 1, min: Math.min(...s), max: Math.max(...s), empty: s.filter((v) => v <= 0).length }
  }), [soc, n])
  const lowest = useMemo(() => Math.min(...soc), [soc])
  const cur = Math.min(Math.max(Math.floor(now), 0), n - 1)
  const hourAt = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const vx = ((e.clientX - r.left) / r.width) * W
    return Math.min(n - 1, Math.max(0, Math.round(((vx - PAD_L) / (W - PAD_L)) * (n - 1))))
  }
  const fmtHour = (i) => new Date(startMs + i * 3600_000).toISOString().replace('T', ' ').slice(5, 16) + ' UTC'

  return (
    <figure className="relative mt-3" aria-label="Battery charge over the mission">
      <div className="mb-1 flex items-center justify-between text-[10px] text-mute">
        <span>Battery charge over the mission</span>
        <span className="num text-ink">now {fmt(soc[cur], 0)}%</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label={`Battery charge over the mission: lowest ${fmt(lowest, 0)}%, ${days.reduce((a, d) => a + d.empty, 0)} hours without power`}
        className="h-[80px] w-full cursor-crosshair rounded-md border border-line/70 bg-bg/60"
        onMouseMove={(e) => setHover(hourAt(e))} onMouseLeave={() => setHover(null)}>
        {dark.map(([a, b]) => <rect key={`d${a}`} x={x(a)} y={0} width={Math.max(x(b) - x(a), 0.5)} height={H} fill={NIGHT} opacity="0.9" />)}
        {[0, 50, 100].map((p) => (
          <g key={p}>
            <line x1={PAD_L} x2={W} y1={y(p)} y2={y(p)} stroke={GRID} strokeWidth="0.5" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
            <text x={PAD_L - 3} y={y(p) + 2.5} textAnchor="end" fontSize="7" fill={NEUTRAL}>{p}%</text>
          </g>
        ))}
        <path d={`${line}L${W},${H - 4}L${PAD_L},${H - 4}Z`} fill={SERIES} opacity="0.14" />
        <path d={line} fill="none" stroke={SERIES} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {empty.map(([a, b]) => <rect key={`e${a}`} x={x(a)} y={H - 7} width={Math.max(x(b) - x(a), 1.5)} height={5} rx="1" fill={CRITICAL} />)}
        <line x1={x(cur)} x2={x(cur)} y1={0} y2={H} stroke={NEUTRAL} strokeWidth="1" strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />
        {hover != null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} stroke={NEUTRAL} strokeWidth="1" vectorEffect="non-scaling-stroke" />
            <circle cx={x(hover)} cy={y(soc[hover])} r="2.6" fill={SERIES} stroke="#0b1120" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
          </g>
        )}
      </svg>
      {hover != null && (
        <div role="tooltip" className="num pointer-events-none absolute z-20 rounded-md border border-line bg-panel2 px-2 py-1 text-[10.5px] text-ink shadow-lg"
          style={{ left: `${Math.min(62, Math.max(0, (x(hover) / W) * 100 - 14))}%`, top: 18 }}>
          <div className="text-mute">{fmtHour(hover)}</div>
          <div>charge <b>{fmt(soc[hover], 1)}%</b> · solar <b>{fmt(power[hover], 0)} W</b></div>
        </div>
      )}
      <figcaption className="num mt-1 flex justify-between gap-2 text-[9.5px] text-mute">
        <span>{new Date(startMs).toISOString().slice(5, 10)}</span>
        <span>
          <i className="mr-1 inline-block h-2 w-2 rounded-sm align-middle ring-1 ring-line" style={{ background: NIGHT }} />Sun hidden
          <i className="ml-2 mr-1 inline-block h-2 w-2 rounded-sm align-middle" style={{ background: CRITICAL }} />✕ no power
          <i className="ml-2 mr-1 inline-block h-0.5 w-3 align-middle" style={{ background: NEUTRAL }} />now
        </span>
        <span>+{Math.round(n / 24)} d</span>
      </figcaption>
      <details className="mt-1 text-[10px] text-mute">
        <summary className="cursor-pointer select-none hover:text-ink">Show data as a table</summary>
        <div className="mt-1 max-h-40 overflow-y-auto">
          <table className="num w-full text-left">
            <thead><tr><th className="pr-2 font-normal">Day</th><th className="pr-2 font-normal">Lowest</th><th className="pr-2 font-normal">Highest</th><th className="font-normal">Hours without power</th></tr></thead>
            <tbody className="text-ink">{days.map((d) => <tr key={d.day}><td>{d.day}</td><td>{fmt(d.min, 0)}%</td><td>{fmt(d.max, 0)}%</td><td>{d.empty || '-'}</td></tr>)}</tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}

/**
 * Power survival - the energy check judges look at first: does the battery carry the lander through the longest lunar night?
 * Hourly energy balance of this site's solar power (current tilt, area, mast) against a constant load, starting fully charged.
 */
export default function SurvivalCard({ calc, scn, onPatch }) {
  const capacity = scn.batteryKwh, load = scn.loadW // kWh usable, W constant (avionics + survival heaters); shared with the map
  const setCapacity = (v) => onPatch({ batteryKwh: v }), setLoad = (v) => onPatch({ loadW: v })
  const r = useMemo(() => {
    const sim = simulateBattery(calc.power, capacity, load, true)
    return { ...sim, need: requiredCapacityKwh(calc.power, load), dark: longestDarkHours(calc.power) }
  }, [calc, capacity, load])
  const ok = r.survives
  const reachable = Number.isFinite(r.need)
  const needPct = reachable ? Math.min(100, (r.need / Math.max(capacity, r.need)) * 100) : 100
  const capPct = reachable ? Math.min(100, (capacity / Math.max(capacity, r.need)) * 100) : 0
  const margin = reachable ? capacity - r.need : -Infinity
  const verdict = STATUS_CUE[ok ? 'good' : 'critical']

  return (
    <Card title="Power survival" accent={ok ? 'text-go' : 'text-nogo'} right={<InfoTip text={GLOSSARY.battery} />}
      className={cx('border-2', ok ? 'border-go/50' : 'border-nogo/60')}>
      <div role="status" className="mb-3 flex items-center justify-between gap-3 rounded-lg border px-3 py-2"
        style={{ borderColor: `${verdict.color}80`, background: `${verdict.color}1a` }}>
        <div>
          <div className="text-[15px] font-bold tracking-wide" style={{ color: verdict.color }}>{verdict.icon} {ok ? 'SURVIVES THE MISSION' : 'BATTERY RUNS OUT'}</div>
          <div className="text-[10.5px] text-mute">{ok ? `Lowest charge ${fmt(r.minSocPct, 0)}%, ${fmt(margin, 1)} kWh spare capacity` : `${r.hoursEmpty} h without power; first at mission hour ${r.firstEmptyHour}`}</div>
        </div>
        <div className="num text-right text-[10.5px] text-mute">{capacity} kWh<br />{load} W load</div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Battery needed" value={reachable ? fmt(r.need, 1) : '> 5000'} unit="kWh"
          status={ok ? 'good' : 'critical'} statusText={ok ? `fits in ${capacity} kWh` : `more than your ${capacity} kWh`} />
        <Stat label="Lowest charge" value={fmt(r.minSocPct, 0)} unit="%"
          status={r.minSocPct <= 0 ? 'critical' : r.minSocPct < 20 ? 'warning' : 'good'}
          statusText={r.minSocPct <= 0 ? 'battery empties' : r.minSocPct < 20 ? 'thin reserve' : 'healthy reserve'} />
        <Stat label="Longest night" value={r.dark} unit="h" sub={`${fmt(r.dark / 24, 1)} days without Sun`} />
        <Stat label="Hours without power" value={r.hoursEmpty} unit="h"
          status={r.hoursEmpty ? 'critical' : 'good'} statusText={r.hoursEmpty ? 'lander loses power' : 'never empty'} />
      </div>

      <div className="mt-3" aria-label="Battery capacity compared with the battery needed">
        <div className="mb-1 flex justify-between text-[10px] text-mute">
          <span>Capacity vs need</span>
          <span className="num text-ink">{reachable ? `${margin >= 0 ? '+' : ''}${fmt(margin, 1)} kWh` : 'not reachable'}</span>
        </div>
        <div className="relative h-2.5 overflow-hidden rounded-full bg-panel2">
          <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${capPct}%`, background: SERIES }} />
          <div className="absolute inset-y-0 w-0.5 bg-ink" style={{ left: `calc(${needPct}% - 1px)` }} title="battery needed" />
        </div>
        <div className="mt-0.5 flex justify-between text-[9.5px] text-mute"><span>blue = your battery</span><span>white mark = needed</span></div>
      </div>

      <ChargeChart soc={r.socPct} power={calc.power} startMs={calc.startMs} />

      <div className="num mt-2 grid grid-cols-3 gap-2 text-center text-[10px] text-mute">
        <div><div className="text-[13px] font-semibold text-ink">{fmt(r.generatedKwh, 0)}</div>kWh generated</div>
        <div><div className="text-[13px] font-semibold text-ink">{fmt(r.consumedKwh, 0)}</div>kWh used by load</div>
        <div><div className="text-[13px] font-semibold text-ink">{fmt(r.wastedKwh, 0)}</div>kWh unstored (full)</div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Num label="Battery" unit="kWh" value={capacity} onChange={setCapacity} min={1} max={2000} step={5} />
        <Num label="Constant load" unit="W" value={load} onChange={setLoad} min={10} max={20000} step={10} />
      </div>
    </Card>
  )
}
