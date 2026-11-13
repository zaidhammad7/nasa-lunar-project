// Battery survival through the mission window: hourly energy balance of solar input vs a constant load.

/**
 * Simulate state of charge hour by hour (starts full; charging capped at capacity).
 * @param powerW       hourly solar power (W)
 * @param capacityKwh  usable battery capacity (kWh)
 * @param loadW        constant load incl. survival heaters (W)
 * @returns {survives, minSocPct, hoursEmpty, firstEmptyHour, endSocPct}
 */
export function simulateBattery(powerW, capacityKwh, loadW) {
  let soc = capacityKwh, min = capacityKwh, empty = 0, first = -1
  for (let i = 0; i < powerW.length; i++) {
    soc = Math.min(capacityKwh, soc + (powerW[i] - loadW) / 1000)
    if (soc <= 0) { soc = 0; empty++; if (first < 0) first = i }
    if (soc < min) min = soc
  }
  const pct = (v) => (capacityKwh > 0 ? (v / capacityKwh) * 100 : 0)
  return { survives: empty === 0, minSocPct: pct(min), hoursEmpty: empty, firstEmptyHour: first, endSocPct: pct(soc) }
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
