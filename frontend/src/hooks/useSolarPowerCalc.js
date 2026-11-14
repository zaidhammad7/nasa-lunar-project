// Instant (60 FPS) hardware maths: panel tilt and panel area re-derive the whole power curve, illumination states and
// window statistics from the backend's hourly elevations without waiting. Tower height is NOT re-estimated here: the backend
// re-ray-traces the terrain horizon from the mast top (a mast clears nearby crater walls by atan(h / d), which no local shift can
// reproduce), so the shown values change once, when that result arrives, instead of jumping to a guess and back.
import { useMemo } from 'react'
import {
  towerBoostDeg, powerWatts, sunDiscFraction, stateCode, STATE_NAMES, DTE_CONNECTED, DTE_BLOCKED, nextEvent,
  BASELINE_START_MS, HOUR_MS,
} from '../lib/physics.js'

/**
 * @param result  backend (or offline) evaluation containing `timeline` and `scenario.hardware`
 * @param hw      {tower, tilt, area} - the values currently shown in the UI
 */
export function useSolarPowerCalc(result, hw) {
  return useMemo(() => {
    const tl = result?.timeline
    if (!tl) return null
    const n = tl.sun_el_eff_deg.length
    const boost = towerBoostDeg(result.scenario.hardware.tower_height_m) // geometric dip of the evaluated mast (informational)
    const sunEff = new Float64Array(n), earthEff = new Float64Array(n), power = new Float64Array(n), cum = new Float64Array(n)
    const state = new Uint8Array(n), disc = new Float32Array(n)
    let lit = 0, dte = 0, acc = 0, peak = 0, maxSun = -Infinity, maxEarth = -Infinity, sumSun = 0, sumEarth = 0
    for (let i = 0; i < n; i++) {
      const s = tl.sun_el_eff_deg[i] // elevation above the terrain horizon seen from the evaluated mast
      const e = tl.earth_el_eff_deg[i]
      sunEff[i] = s; earthEff[i] = e; state[i] = stateCode(s); disc[i] = sunDiscFraction(s)
      power[i] = powerWatts(s, hw.area, hw.tilt); acc += power[i] / 1000; cum[i] = acc
      if (s > 0) lit++
      if (e > 0) dte++
      if (power[i] > peak) peak = power[i]
      if (s > maxSun) maxSun = s
      if (e > maxEarth) maxEarth = e
      sumSun += s; sumEarth += e
    }
    const startMs = Date.parse(result.scenario.start_datetime_utc)
    const startIdx = Math.round((startMs - BASELINE_START_MS) / HOUR_MS)
    return {
      n, sunEff, earthEff, power, cum, state, disc, startMs, startIdx, boost,
      stats: { sunVisPct: (lit / n) * 100, earthVisPct: (dte / n) * 100, sunMax: maxSun, earthMax: maxEarth, sunAvg: sumSun / n, earthAvg: sumEarth / n,
        sunHours: lit, avgPower: acc * 1000 / n, peakPower: peak, totalKwh: acc },
      /** Live values at mission hour `i` (integer). */
      at(i) {
        const k = Math.min(Math.max(Math.floor(i), 0), n - 1)
        return {
          i: k, sunEl: sunEff[k], earthEl: earthEff[k], state: STATE_NAMES[state[k]], disc: disc[k], power: power[k], cumKwh: cum[k],
          dte: earthEff[k] > 0 ? DTE_CONNECTED : DTE_BLOCKED, connected: earthEff[k] > 0, lit: sunEff[k] > 0,
          timeMs: startMs + k * HOUR_MS,
        }
      },
      /** Countdowns from hour `i` (scans the mission-window series). */
      countdown(i) {
        const k = Math.min(Math.max(Math.floor(i), 0), n - 1)
        return { sun: nextEvent(sunEff, k, startMs), earth: nextEvent(earthEff, k, startMs) }
      },
    }
  }, [result, hw.tilt, hw.area])
}
