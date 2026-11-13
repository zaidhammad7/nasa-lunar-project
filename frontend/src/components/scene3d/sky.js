// Per-frame sky state shared by all 3-D components (written once per frame by <SkyClock/>, read everywhere).
import { sunDirection, earthDirection } from '../../lib/physics.js'
import { timeStore } from '../../lib/timeStore.js'

export const sky = {
  sun: [0, 0, 1], // unit vector Moon -> Sun in the Moon-fixed scene frame
  earth: [0, 0, 1], // unit vector Moon -> Earth (moves with libration)
  absHours: 0,
}

/** Recompute from the mission clock: Sun on the 708.73 h synodic cycle, Earth on the 653.09 h / 661.31 h libration cycles. */
export function updateSky() {
  const t = timeStore.absHours()
  sky.absHours = t
  sky.sun = sunDirection(t)
  sky.earth = earthDirection(t)
}

// Stylised (not to scale) distances: compressed so the Sun and Earth stay in frame around the Moon.
export const SUN_DISTANCE = 3.1
export const EARTH_DISTANCE = 2.05
