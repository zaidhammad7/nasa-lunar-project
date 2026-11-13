import { useMemo } from 'react'
import { useTimeHours } from '../../lib/timeStore.js'

/** Tiny SVG chart of an hourly series with a zero line and a live cursor bound to the mission clock. */
export default function Sparkline({ data, color = '#38bdf8', fill = false, zero = false, height = 54, min, max, label }) {
  const W = 300
  const { path, area, y0, lo, hi } = useMemo(() => {
    if (!data || !data.length) return { path: '', area: '', y0: null, lo: 0, hi: 1 }
    const n = data.length, pts = Math.min(240, n)
    let lo = min ?? Infinity, hi = max ?? -Infinity
    if (min == null || max == null) for (let i = 0; i < n; i++) { if (min == null && data[i] < lo) lo = data[i]; if (max == null && data[i] > hi) hi = data[i] }
    if (hi - lo < 1e-6) hi = lo + 1
    const y = (v) => height - 3 - ((v - lo) / (hi - lo)) * (height - 6)
    const seg = []
    for (let k = 0; k < pts; k++) { const i = Math.round((k / (pts - 1)) * (n - 1)); seg.push(`${((k / (pts - 1)) * W).toFixed(1)},${y(data[i]).toFixed(1)}`) }
    const path = 'M' + seg.join('L')
    return { path, area: `${path}L${W},${height}L0,${height}Z`, y0: zero && lo < 0 && hi > 0 ? y(0) : null, lo, hi }
  }, [data, height, min, max, zero])
  const h = useTimeHours(66)
  const x = data && data.length > 1 ? (Math.min(h, data.length - 1) / (data.length - 1)) * W : 0
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="w-full" style={{ height }} role="img" aria-label={label}>
      {fill && <path d={area} fill={color} opacity={0.16} />}
      {y0 != null && <line x1="0" x2={W} y1={y0} y2={y0} stroke="#475569" strokeDasharray="3 3" strokeWidth="1" />}
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
      <line x1={x} x2={x} y1="0" y2={height} stroke="#f1f5f9" strokeWidth="1" opacity="0.85" />
      <text x="2" y="9" fontSize="8" fill="#94a3b8" className="num">{hi.toFixed(hi > 100 ? 0 : 1)}</text>
      <text x="2" y={height - 2} fontSize="8" fill="#94a3b8" className="num">{lo.toFixed(lo > 100 ? 0 : 1)}</text>
    </svg>
  )
}
