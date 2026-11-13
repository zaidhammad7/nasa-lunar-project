// Tiny external store for the mission clock. The 3D scene reads `hours` directly every frame (no React work);
// React components subscribe through useTimeHours(), which throttles re-renders so 60x playback stays smooth.
import { useEffect, useState } from 'react'

const listeners = new Set()

export const timeStore = {
  hours: 0, // hours since the start of the mission window (fractional while playing)
  length: 1440, // mission length (hours)
  startOffset: 0, // mission start, hours after 2026-11-13T00:00Z
  playing: false,
  speed: 10, // simulated hours per real second
  set(h, notify = true) {
    this.hours = Math.min(Math.max(h, 0), Math.max(this.length - 1, 0))
    if (notify) listeners.forEach((fn) => fn())
  },
  configure(length, startOffset) {
    this.length = length
    this.startOffset = startOffset
    this.hours = Math.min(this.hours, Math.max(length - 1, 0))
    listeners.forEach((fn) => fn())
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
  /** Absolute hours after the baseline start (what the ephemeris models take). */
  absHours() { return this.startOffset + this.hours },
}

/** Current mission hour for React components; `throttleMs` bounds the re-render rate. */
export function useTimeHours(throttleMs = 66) {
  const [h, setH] = useState(timeStore.hours)
  useEffect(() => {
    let last = 0, pending = null
    const fn = () => {
      const now = performance.now()
      if (now - last >= throttleMs) { last = now; setH(timeStore.hours) }
      else if (!pending) pending = setTimeout(() => { pending = null; last = performance.now(); setH(timeStore.hours) }, throttleMs)
    }
    setH(timeStore.hours)
    const off = timeStore.subscribe(fn)
    return () => { off(); if (pending) clearTimeout(pending) }
  }, [throttleMs])
  return h
}

/** Re-render when length / start offset / play state change (rare events). */
export function useTimeMeta() {
  const [, force] = useState(0)
  useEffect(() => timeStore.subscribe(() => force((n) => n + 1)), [])
  return { length: timeStore.length, startOffset: timeStore.startOffset, playing: timeStore.playing, speed: timeStore.speed }
}
