// Suitability heatmap for the -85..-90 deg study cap: inverse-distance-weighted interpolation of the 100 scored sites
// onto an equirectangular canvas that matches three.js sphere UVs (u = 0 at lon 180 deg; row 0 = lat -85, last = -90).

export const CAP_LAT_MIN = -85 // deg, edge of the study cap
export const HEAT_RANGE = [40, 90] // score mapped to the colour ramp (red .. amber .. green)

/** Polar-plane position (deg from the pole), so interpolation does not blow up near the pole. */
const polar = (lat, lon) => { const r = 90 + lat, a = (lon * Math.PI) / 180; return [r * Math.cos(a), r * Math.sin(a)] }

/** Score -> [r, g, b]: red (low) -> amber -> green (high). */
export function rampColor(score) {
  const t = Math.min(1, Math.max(0, (score - HEAT_RANGE[0]) / (HEAT_RANGE[1] - HEAT_RANGE[0])))
  const stops = [[239, 68, 68], [245, 158, 11], [16, 185, 129]]
  const k = t < 0.5 ? 0 : 1, f = t < 0.5 ? t * 2 : (t - 0.5) * 2
  return stops[k].map((c, i) => Math.round(c + (stops[k + 1][i] - c) * f))
}

/**
 * Paint the interpolated score field.
 * @param sites  [{lat, lon, score}] (deg, deg E, 0-100)
 * @param w,h    canvas size (px): longitude x latitude
 * @param power  IDW exponent
 */
export function buildHeatCanvas(sites, w = 512, h = 48, power = 2) {
  const c = document.createElement('canvas'); c.width = w; c.height = h
  const ctx = c.getContext('2d'), img = ctx.createImageData(w, h)
  const pts = sites.map((s) => ({ p: polar(s.lat, s.lon), v: s.score }))
  for (let y = 0; y < h; y++) {
    const lat = CAP_LAT_MIN - ((y + 0.5) / h) * (90 + CAP_LAT_MIN)
    for (let x = 0; x < w; x++) {
      const lon = (((x + 0.5) / w) * 360 + 180) % 360
      const [px, py] = polar(lat, lon)
      let sw = 0, sv = 0
      for (const q of pts) { const d2 = (q.p[0] - px) ** 2 + (q.p[1] - py) ** 2; const wt = 1 / Math.pow(Math.max(d2, 1e-6), power / 2); sw += wt; sv += wt * q.v }
      const [r, g, b] = rampColor(sv / sw), o = (y * w + x) * 4
      img.data[o] = r; img.data[o + 1] = g; img.data[o + 2] = b; img.data[o + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
  return c
}
