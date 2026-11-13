export const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d))
export const fmtInt = (v) => (v == null || Number.isNaN(v) ? '—' : Math.round(v).toLocaleString('en-US'))
export const fmtW = (w) => (w == null ? '—' : w >= 1000 ? `${(w / 1000).toFixed(2)} kW` : `${w.toFixed(0)} W`)
export const fmtUtc = (ms) => new Date(ms).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
export const sign = (v, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}`)

/** "Xd Xh Xm" from fractional hours. */
export function fmtDHM(hours) {
  if (hours == null) return '—'
  const total = Math.round(hours * 60)
  return `${Math.floor(total / 1440)}d ${Math.floor((total % 1440) / 60)}h ${total % 60}m`
}

export const STATUS = {
  Optimal: { label: 'GO / Optimal', color: 'text-go', bg: 'bg-go/15', border: 'border-go/50', hex: '#10B981' },
  Acceptable: { label: 'CONDITIONAL / Acceptable', color: 'text-solar', bg: 'bg-solar/15', border: 'border-solar/50', hex: '#F59E0B' },
  Hazardous: { label: 'NO-GO / Hazardous', color: 'text-nogo', bg: 'bg-nogo/15', border: 'border-nogo/50', hex: '#F43F5E' },
}
export const classHex = (c) => (STATUS[c] || STATUS.Hazardous).hex

export const cx = (...a) => a.filter(Boolean).join(' ')
