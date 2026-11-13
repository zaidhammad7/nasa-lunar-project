// Timestamped hourly telemetry -> mission_telemetry_export.csv (backend export when online, client-built otherwise).
import { useCallback, useState } from 'react'
import { exportCsvBlob, buildBody } from '../api/lunarModelApi.js'
import { crossingTimes, DTE_CONNECTED, DTE_BLOCKED, STATE_NAMES, stateCode, powerWatts } from '../lib/physics.js'

export const CSV_COLUMNS = ['timestamp_utc', 'hour_index', 'illumination_state', 'sun_el_eff_deg', 'dte_status', 'earth_el_eff_deg',
  'time_to_sunset_hrs', 'time_to_earthset_hrs', 'power_watts', 'cumulative_energy_kwh']

/** Build the CSV text from the live (instantly recomputed) series; same 10 columns as POST /api/export-csv. */
export function buildCsvFromCalc(result, calc, hw) {
  const n = calc.n
  const nextDown = (arr) => {
    const ct = crossingTimes(arr, 'down')
    return (i) => { const c = ct.find((x) => x >= i); return c == null ? '' : (c - i).toFixed(4) }
  }
  const tS = nextDown(calc.sunEff), tE = nextDown(calc.earthEff)
  const lines = [CSV_COLUMNS.join(',')]
  let cum = 0
  for (let i = 0; i < n; i++) {
    const p = powerWatts(calc.sunEff[i], hw.area, hw.tilt)
    cum += p / 1000
    lines.push([result.timeline.timestamp_utc[i], i, STATE_NAMES[stateCode(calc.sunEff[i])], calc.sunEff[i].toFixed(4),
      calc.earthEff[i] > 0 ? DTE_CONNECTED : DTE_BLOCKED, calc.earthEff[i].toFixed(4), tS(i), tE(i), p.toFixed(3), cum.toFixed(5)].join(','))
  }
  return lines.join('\n') + '\n'
}

function download(blob, name = 'mission_telemetry_export.csv') {
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export function useCsvExporter(scenario, mode, result, calc) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const run = useCallback(async () => {
    if (!result || !scenario) return
    setBusy(true); setNote(null)
    try {
      if (result._source === 'live') {
        try { download(await exportCsvBlob(buildBody(scenario, mode))); setNote('Exported from backend (/api/export-csv)'); return } catch { /* fall through to local */ }
      }
      if (calc) { download(new Blob([buildCsvFromCalc(result, calc, scenario ? { tilt: scenario.tilt, area: scenario.area } : { tilt: 45, area: 10 })], { type: 'text/csv' })); setNote('Exported from local telemetry (offline)') }
    } finally { setBusy(false) }
  }, [scenario, mode, result, calc])
  return { exportCsv: run, busy, note }
}
