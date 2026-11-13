// "Export CSV": a one-point mission summary built client-side from the live (instantly recomputed) telemetry, so it always
// matches what is on screen, including the current tower / tilt / area. Field,Value rows only (site, coordinates, mode,
// score, status, terrain, hardware, totals) - no hourly table.
import { useCallback, useState } from 'react'

const esc = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }
const row = (cells) => cells.map(esc).join(',')

export function buildMissionCsv({ result, calc, scn, mode, liveScore }) {
  const d = result.primary_landing_decision
  const t = result.terrain_topography_physics
  const score = liveScore ?? d.Suitability_Score
  const site = scn.siteId || 'Custom Selected Point'
  const summary = [
    ['MISSION SUMMARY', ''],
    ['Site_ID', site], ['Latitude_deg', scn.lat.toFixed(4)], ['Longitude_deg_E', scn.lon.toFixed(4)], ['Priority_Mode', mode],
    ['Suitability_Score', Number(score).toFixed(2)], ['Safety_Status', d.mission_status_label],
    ['Model_Confidence_Pct', d.model_confidence_pct == null ? 'n/a (offline estimate)' : d.model_confidence_pct],
    ['Slope_deg', t.Slope_deg], ['Elevation_m', t.Elevation_m], ['Roughness_m', t.Roughness_m ?? ''],
    ['Tower_Height_m', scn.tower], ['Panel_Tilt_deg', scn.tilt], ['Panel_Area_m2', scn.area],
    ['Mission_Start_UTC', result.scenario.start_datetime_utc], ['Mission_Duration_Hours', calc.n],
    ['Total_Sunlight_Pct', calc.stats.sunVisPct.toFixed(2)], ['Total_Earth_Comms_Pct', calc.stats.earthVisPct.toFixed(2)],
    ['Peak_Power_W', calc.stats.peakPower.toFixed(1)], ['Average_Power_W', calc.stats.avgPower.toFixed(1)],
    ['Total_Accumulated_Energy_kWh', calc.stats.totalKwh.toFixed(3)],
    ['Data_Source', result._source === 'live' ? 'live backend' : 'offline analytic fallback'], ['Generated_UTC', new Date().toISOString()],
  ]
  const lines = summary.map(row)
  return lines.join('\r\n') + '\r\n'
}

export const csvFileName = (scn, result) => {
  const date = result.scenario.start_datetime_utc.slice(0, 10)
  const site = scn.siteId || `custom_${scn.lat.toFixed(4)}_${scn.lon.toFixed(4)}`.replace('-', 'm')
  return `lunar_mission_telemetry_${site}_${date}.csv`
}

export function useCsvExporter(scn, mode, result, calc, liveScore) {
  const [note, setNote] = useState(null)
  const exportCsv = useCallback(() => {
    if (!result || !calc) return
    const text = buildMissionCsv({ result, calc, scn, mode, liveScore })
    const name = csvFileName(scn, result)
    const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' })) // BOM so Excel reads UTF-8
    const a = Object.assign(document.createElement('a'), { href: url, download: name })
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
    setNote(`Saved ${name}`)
    setTimeout(() => setNote(null), 4000)
  }, [scn, mode, result, calc, liveScore])
  return { exportCsv, note }
}
