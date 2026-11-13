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

// TRUE scale: 1 unit = lunar radius = 1737.4 km.
export const MOON_RADIUS = 1.0
export const EARTH_RADIUS = 3.668 // 6371 km
export const EARTH_DISTANCE = 221.2 // 384,400 km
export const SUN_RADIUS = 400.8 // 696,340 km
export const SUN_DISTANCE = 86105 // 149,600,000 km (subtends 0.53 deg)
