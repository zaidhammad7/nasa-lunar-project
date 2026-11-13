// Debug switches for profiling the 3-D scene. Append ?perf=probe,noshadow,nolines,nostars,lowres to the URL.
//   probe    : time every requestAnimationFrame callback (JS cost per frame, independent of vsync / pane visibility)
//   noshadow : disable shadow maps      nolines : hide terminator + rays      nostars : hide the star field
//   lowres   : device-pixel-ratio 1
const flags = new Set((new URLSearchParams(typeof location !== 'undefined' ? location.search : '').get('perf') || '').split(',').filter(Boolean))
export const perfFlag = (name) => flags.has(name)

/** Wraps requestAnimationFrame so window.__probe holds per-callback JS time and frame intervals (call before React mounts). */
export function installProbe() {
  if (!flags.has('probe')) return
  const orig = window.requestAnimationFrame.bind(window)
  const p = (window.__probe = { n: 0, jsMs: 0, maxJs: 0, last: 0, gaps: [], reset() { this.n = 0; this.jsMs = 0; this.maxJs = 0; this.gaps = [] },
    report() { const g = [...this.gaps].sort((a, b) => a - b); return { callbacks: this.n, avgJsMsPerCallback: +(this.jsMs / Math.max(this.n, 1)).toFixed(2), maxJsMs: +this.maxJs.toFixed(1), medianFrameGapMs: +(g[g.length >> 1] || 0).toFixed(1), p95FrameGapMs: +(g[Math.floor(g.length * 0.95)] || 0).toFixed(1) } } })
  window.requestAnimationFrame = (cb) => orig((ts) => {
    const a = performance.now()
    cb(ts)
    const d = performance.now() - a
    p.n++; p.jsMs += d; if (d > p.maxJs) p.maxJs = d
    if (p.last) p.gaps.push(ts - p.last)
    p.last = ts
  })
}
