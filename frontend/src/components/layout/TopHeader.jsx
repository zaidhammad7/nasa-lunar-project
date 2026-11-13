import { cx } from '../../lib/format.js'
import { API_URL } from '../../api/lunarModelApi.js'

function BackendBadge({ backend, loading, onWarmup }) {
  const h = backend.health
  if (backend.online === null) return <span className="num flex items-center gap-1.5 text-[11px] text-mute"><i className="h-2 w-2 animate-pulse rounded-full bg-mute" />connecting…</span>
  if (!backend.online) {
    return (
      <span className="num flex items-center gap-1.5 rounded-md border border-solar/50 bg-solar/10 px-2 py-1 text-[11px] text-solar" title={`Backend ${API_URL} unreachable${backend.lastError ? ` (${backend.lastError})` : ''}. Using the built-in calibrated physics fallback.`}>
        <i className="h-2 w-2 rounded-full bg-solar" />OFFLINE · analytic fallback
      </span>
    )
  }
  return (
    <button onClick={onWarmup} title={h ? `models ${h.models_ready ? 'ready' : 'loading'} · DEM ${h.dem_ready ? 'ready' : 'opening'} · demo cache ${h.cached_demo_sites}/${h.demo_sites_total ?? 5} · warm-up ${h.warmup_latency_ms} ms · click to run POST /api/warmup` : 'backend live'}
      className="num flex items-center gap-2 rounded-md border border-go/40 bg-go/10 px-2 py-1 text-[11px] text-go hover:bg-go/15">
      <i className={cx('h-2 w-2 rounded-full bg-go', loading && 'animate-pulse')} />BACKEND LIVE
      {h && <span className="hidden text-mute xl:inline">DEM {h.dem_ready ? '✓' : '…'} · cache {h.cached_demo_sites}/5 · SF {h.safety_factor_active ? '✓' : '✗'} · {Math.round(h.warmup_latency_ms ?? 0)} ms</span>}
    </button>
  )
}

/** App title, backend health badge, Compare Sites toggle and CSV export. */
export default function TopHeader({ backend, loading, error, compareOn, onToggleCompare, onExport, exporting, onWarmup }) {
  return (
    <header className="glass z-30 flex h-12 shrink-0 items-center gap-4 border-b border-line px-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <svg viewBox="0 0 32 32" className="h-6 w-6 shrink-0"><circle cx="16" cy="16" r="14" fill="#cbd5e1" /><circle cx="11" cy="12" r="3" fill="#94a3b8" /><circle cx="20" cy="20" r="4" fill="#94a3b8" /><circle cx="21" cy="9" r="2" fill="#94a3b8" /><path d="M2 20a14 14 0 0 0 28 0z" fill="#0b1120" opacity=".35" /></svg>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[13px] font-bold tracking-wide">LUNAR LANDING SITE NAVIGATOR</div>
          <div className="truncate text-[10px] uppercase tracking-[0.16em] text-mute">South Pole Mission Control · NASA Space Apps 2026</div>
        </div>
      </div>
      <div className="min-w-0 flex-1 text-center">
        {error && <span className="num inline-block max-w-full truncate rounded-md border border-nogo/50 bg-nogo/10 px-2 py-0.5 text-[11px] text-nogo" title={error}>⚠ {error}</span>}
      </div>
      <BackendBadge backend={backend} loading={loading} onWarmup={onWarmup} />
      <label className="flex cursor-pointer items-center gap-2 text-[12px] font-medium select-none">
        <span className={compareOn ? 'text-scenb' : 'text-mute'}>Compare sites</span>
        <button role="switch" aria-checked={compareOn} onClick={onToggleCompare}
          className={cx('relative h-5 w-9 rounded-full border transition-colors', compareOn ? 'border-scenb bg-scenb/30' : 'border-line bg-panel2')}>
          <i className={cx('absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all', compareOn ? 'left-[18px] bg-scenb' : 'left-0.5 bg-mute')} />
        </button>
      </label>
      <button onClick={onExport} disabled={exporting}
        className="flex items-center gap-1.5 rounded-md border border-earth/60 bg-earth/15 px-3 py-1.5 text-[12px] font-semibold text-earth transition-colors hover:bg-earth/25 disabled:opacity-50">
        <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor"><path d="M10 2a1 1 0 0 1 1 1v8.6l2.3-2.3a1 1 0 1 1 1.4 1.4l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L9 11.6V3a1 1 0 0 1 1-1zM4 15a1 1 0 0 1 1 1v1h10v-1a1 1 0 1 1 2 0v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1a1 1 0 0 1 1-1z" /></svg>
        {exporting ? 'Exporting…' : 'Export CSV'}
      </button>
    </header>
  )
}
