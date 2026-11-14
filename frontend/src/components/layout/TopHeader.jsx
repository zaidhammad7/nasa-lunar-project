import { useEffect, useState } from 'react'
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
    <button onClick={onWarmup} title={h ? `models ${h.models_ready ? 'ready' : 'loading'} · DEM ${h.dem_ready ? 'ready' : 'opening'} · reference sites ${h.cached_demo_sites}/${h.demo_sites_total ?? 5} · preload ${h.warmup_latency_ms} ms · click to preload` : 'backend live'}
      className="num flex items-center gap-2 rounded-md border border-go/40 bg-go/10 px-2 py-1 text-[11px] text-go hover:bg-go/15">
      <i className={cx('h-2 w-2 rounded-full bg-go', loading && 'animate-pulse')} />BACKEND LIVE
      {h && <span className="hidden text-mute xl:inline">DEM {h.dem_ready ? '✓' : '…'} · cache {h.cached_demo_sites}/5 · SF {h.safety_factor_active ? '✓' : '✗'}</span>}
    </button>
  )
}

/** Shown when the backend runs without the downloaded NASA terrain / illumination data (e.g. a fresh clone). */
function DataWarning({ health }) {
  if (!health || (health.horizon_dem_ready !== false && health.terrain_shadowing_ready !== false)) return null
  return (
    <span role="alert" className="num flex max-w-[22rem] items-center gap-1.5 truncate rounded-md border border-solar/60 bg-solar/10 px-2 py-1 text-[11px] text-solar"
      title="The 100 preset sites use stored NASA horizons and stay accurate. Points you click use a flat horizon, which over-estimates sunlight. Fix: python src/analysis/nasa_data.py (unpacks the NASA LOLA data bundled in nasa_data/), then restart the backend.">
      ⚠ NASA terrain data not downloaded: clicked points less accurate
    </span>
  )
}

/**
 * Result of the last full validation run (python tests/run_all.py -> GET /api/validation): every suite plus the NASA / JPL
 * benchmark. Green when everything passed, red with the failure count otherwise; hover for the per-suite breakdown.
 */
function ValidationBadge({ online }) {
  const [v, setV] = useState(null)
  useEffect(() => {
    if (!online) return undefined
    let dead = false
    fetch(`${API_URL}/api/validation`).then((r) => (r.ok ? r.json() : null)).then((j) => { if (!dead) setV(j) }).catch(() => {})
    return () => { dead = true }
  }, [online])
  if (!v) return null
  const failed = v.total - v.passed
  const tip = [...v.suites.map((s) => `${s.ok ? '✓' : '✕'} ${s.suite}: ${s.passed}/${s.total}${s.failures.length ? ' - ' + s.failures.map((f) => f.case).join('; ') : ''}`), `last run ${v.generated_utc}`].join('\n')
  return (
    <span title={tip} role="status" className={cx('num hidden items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] md:flex', v.ok ? 'border-go/40 bg-go/10 text-go' : 'border-nogo/50 bg-nogo/10 text-nogo')}>
      {v.ok ? `✓ VALIDATED ${v.passed}/${v.total} checks${v.skipped ? ` · ${v.skipped} skipped` : ''}` : `⚠ ${failed} CHECK${failed === 1 ? '' : 'S'} FAILED`}
    </span>
  )
}

/** App title and backend health (the only things in the top bar; the whole bar can be hidden). */
export default function TopHeader({ backend, loading, error, onWarmup }) {
  return (
    <header className="glass z-30 flex h-12 shrink-0 items-center gap-4 border-b border-line px-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <svg viewBox="0 0 32 32" className="h-6 w-6 shrink-0"><circle cx="16" cy="16" r="14" fill="#cbd5e1" /><circle cx="11" cy="12" r="3" fill="#94a3b8" /><circle cx="20" cy="20" r="4" fill="#94a3b8" /><circle cx="21" cy="9" r="2" fill="#94a3b8" /></svg>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[13px] font-bold tracking-wide">LUNAR LANDING SITE NAVIGATOR</div>
          <div className="truncate text-[10px] uppercase tracking-[0.16em] text-mute">South Pole Mission Control · NASA Space Apps 2026</div>
        </div>
      </div>
      <div className="min-w-0 flex-1 text-center">
        {error && <span className="num inline-block max-w-full truncate rounded-md border border-nogo/50 bg-nogo/10 px-2 py-0.5 text-[11px] text-nogo" title={error}>⚠ {error}</span>}
      </div>
      {backend.online === true && <DataWarning health={backend.health} />}
      <ValidationBadge online={backend.online === true} />
      <BackendBadge backend={backend} loading={loading} onWarmup={onWarmup} />
    </header>
  )
}
