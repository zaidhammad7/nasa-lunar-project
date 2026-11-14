// Battery survival through the mission window: hourly energy balance of solar input vs a constant load.

/**
 * Simulate state of charge hour by hour (starts full; charging capped at capacity; never below empty).
 * @param powerW       hourly solar power (W) - one sample per hour, so W x 1 h = Wh
 * @param capacityKwh  usable battery capacity (kWh)
 * @param loadW        constant load incl. survival heaters (W)
 * @param withSeries   also return the hourly state of charge (%) for charting
 * @returns {survives, minSocPct, hoursEmpty, firstEmptyHour, endSocPct, generatedKwh, consumedKwh, wastedKwh, socPct?}
 */
export function simulateBattery(powerW, capacityKwh, loadW, withSeries = false) {
  let soc = capacityKwh, min = capacityKwh, empty = 0, first = -1, gen = 0, wasted = 0
  const series = withSeries ? new Float32Array(powerW.length) : null
  for (let i = 0; i < powerW.length; i++) {
    gen += powerW[i] / 1000
    const next = soc + (powerW[i] - loadW) / 1000
    if (next > capacityKwh) wasted += next - capacityKwh // battery full: surplus solar cannot be stored
    soc = Math.min(capacityKwh, next)
    if (soc <= 0) { soc = 0; empty++; if (first < 0) first = i }
    if (soc < min) min = soc
    if (series) series[i] = capacityKwh > 0 ? (soc / capacityKwh) * 100 : 0
  }
  const pct = (v) => (capacityKwh > 0 ? (v / capacityKwh) * 100 : 0)
  return { survives: empty === 0, minSocPct: pct(min), hoursEmpty: empty, firstEmptyHour: first, endSocPct: pct(soc),
    generatedKwh: gen, consumedKwh: (loadW * powerW.length) / 1000, wastedKwh: wasted, ...(series ? { socPct: series } : {}) }
}

/** Smallest capacity (kWh) that never empties during this window (bisection); Infinity if even maxKwh is not enough. */
export function requiredCapacityKwh(powerW, loadW, maxKwh = 5000) {
  if (!simulateBattery(powerW, maxKwh, loadW).survives) return Infinity
  let lo = 0, hi = maxKwh
  for (let k = 0; k < 40; k++) { const mid = (lo + hi) / 2; if (simulateBattery(powerW, mid, loadW).survives) hi = mid; else lo = mid }
  return hi
}

/** Longest run of consecutive hours with zero solar input (h). */
export function longestDarkHours(powerW) {
  let best = 0, run = 0
  for (const p of powerW) { run = p <= 0 ? run + 1 : 0; if (run > best) best = run }
  return best
}
