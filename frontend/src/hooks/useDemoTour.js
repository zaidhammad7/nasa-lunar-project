// Scripted ~45 s walkthrough for judges: best GO site -> evidence -> heatmap -> timeline -> a NO-GO site -> power survival.
// Every step only drives existing UI actions; pressing the button again (or any timer clear) stops it.
import { useCallback, useEffect, useRef, useState } from 'react'
import { timeStore } from '../lib/timeStore.js'

/** Scroll the right-panel card whose heading text is `title` into view. */
const showCard = (title) => {
  const h = [...document.querySelectorAll('h2')].find((e) => e.textContent.trim().toLowerCase() === title.toLowerCase())
  h?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export function useDemoTour({ sim, setHeatmap, setCraters }) {
  const [running, setRunning] = useState(false)
  const timers = useRef([])
  const simRef = useRef(sim)
  simRef.current = sim

  const stop = useCallback(() => {
    timers.current.forEach(clearTimeout); timers.current = []
    setRunning(false); simRef.current.setPlaying(false)
  }, [])

  const start = useCallback(() => {
    const s0 = simRef.current
    const best = s0.ranking.top5[0] || s0.ranking.all[0]
    const worst = [...s0.ranking.all].reverse().find((x) => x.displayClass === 'Hazardous') || s0.ranking.all.at(-1)
    const steps = [
      [0, () => { setHeatmap(false); setCraters(true); simRef.current.requestFly('cap'); simRef.current.showToast('Demo 1/7 · The lunar South Pole, −85° to −90°, with real NASA LRO imagery and named craters') }],
      [6000, () => { simRef.current.selectSite(best.id); simRef.current.showToast(`Demo 2/7 · Top-ranked site ${best.id}: score, verdict and live telemetry on the right`) }],
      [12000, () => { showCard('Evidence'); simRef.current.showToast('Demo 3/7 · Evidence: each safety check with the measured value and its limit') }],
      [18000, () => { setHeatmap(true); simRef.current.requestFly('cap'); simRef.current.showToast('Demo 4/7 · Suitability heatmap across the whole cap (green = better)') }],
      [24000, () => { timeStore.set(0); simRef.current.setSpeed(60); simRef.current.setPlaying(true); simRef.current.showToast('Demo 5/7 · Mission clock at 60×: Sun and Earth move, countdowns update live') }],
      [31000, () => { simRef.current.setPlaying(false); simRef.current.selectSite(worst.id); simRef.current.showToast(`Demo 6/7 · A NO-GO site (${worst.id}): the checks show exactly why`) }],
      [38000, () => { showCard('Power survival'); simRef.current.showToast('Demo 7/7 · Power survival: does the battery last the longest lunar night?') }],
      [45000, () => { simRef.current.selectSite(best.id); simRef.current.showToast('Demo complete · click anywhere on the Moon to evaluate your own point'); setRunning(false) }],
    ]
    timers.current.forEach(clearTimeout)
    timers.current = steps.map(([ms, fn]) => setTimeout(fn, ms))
    setRunning(true)
  }, [setHeatmap, setCraters])

  useEffect(() => () => timers.current.forEach(clearTimeout), [])
  return { running, toggle: () => (running ? stop() : start()) }
}
