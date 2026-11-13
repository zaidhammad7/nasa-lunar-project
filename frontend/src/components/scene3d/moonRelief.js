// Procedural lunar relief: fractal noise + ~450 craters (denser near the south pole, where the mission is).
// Used for real geometric displacement of the Moon mesh, so the shadow-casting sun produces true crater shadows
// and a physically shaped terminator; pins read the same function to sit on the surface.
import * as THREE from 'three'
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js'

function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const hash3 = (x, y, z) => {
  let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(z, 1274126177)
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295
}
const smooth = (t) => t * t * (3 - 2 * t)
function valueNoise(x, y, z) {
  const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z)
  const xf = smooth(x - xi), yf = smooth(y - yi), zf = smooth(z - zi)
  const l = (a, b, t) => a + (b - a) * t
  const c = (dx, dy, dz) => hash3(xi + dx, yi + dy, zi + dz)
  return l(
    l(l(c(0, 0, 0), c(1, 0, 0), xf), l(c(0, 1, 0), c(1, 1, 0), xf), yf),
    l(l(c(0, 0, 1), c(1, 0, 1), xf), l(c(0, 1, 1), c(1, 1, 1), xf), yf), zf)
}
const fbm = (x, y, z, oct = 4) => {
  let a = 0.5, f = 1, s = 0
  for (let i = 0; i < oct; i++) { s += a * valueNoise(x * f, y * f, z * f); a *= 0.5; f *= 2.03 }
  return s
}

// ---- crater catalogue (deterministic)
const CRATERS = (() => {
  const rnd = mulberry32(2026)
  const out = []
  const push = (dir, r) => out.push({ x: dir[0], y: dir[1], z: dir[2], r, depth: Math.min(0.022, r * 0.16) })
  const randDir = (southBias = 0) => {
    for (;;) {
      const y = southBias ? -1 + rnd() * (1 - Math.cos(southBias)) : rnd() * 2 - 1 // south cap or whole sphere
      const t = rnd() * Math.PI * 2, s = Math.sqrt(1 - y * y)
      return [s * Math.cos(t), y, s * Math.sin(t)]
    }
  }
  for (let i = 0; i < 330; i++) push(randDir(), 0.03 + Math.pow(rnd(), 2.6) * 0.17)
  for (let i = 0; i < 150; i++) push(randDir(0.26), 0.025 + Math.pow(rnd(), 2.4) * 0.11) // dense, rugged south polar cap
  return out
})()

/** Radial relief (fraction of the Moon radius) at a unit direction. */
export function reliefAt(x, y, z) {
  let d = (fbm(x * 2.2 + 11, y * 2.2, z * 2.2) - 0.5) * 0.02 + (fbm(x * 7 + 3, y * 7, z * 7 + 9, 3) - 0.5) * 0.006
  let crater = 0
  for (const c of CRATERS) {
    const dot = x * c.x + y * c.y + z * c.z
    if (dot < 0.97) continue
    const th = Math.acos(Math.min(1, dot)) / c.r
    if (th < 1) crater -= c.depth * (1 - th * th)
    else if (th < 1.7) crater += c.depth * 0.28 * Math.exp(-(((th - 1.08) / 0.2) ** 2))
  }
  return { relief: d + crater, crater }
}

/** Smooth, displaced, vertex-coloured Moon geometry (unit radius). */
export function buildMoonGeometry(detail = 52) {
  let g = new THREE.IcosahedronGeometry(1, detail)
  g.deleteAttribute('normal'); g.deleteAttribute('uv')
  g = mergeVertices(g, 1e-5)
  const pos = g.attributes.position, col = new Float32Array(pos.count * 3)
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i)
    const r = Math.hypot(x, y, z), ux = x / r, uy = y / r, uz = z / r
    const { relief, crater } = reliefAt(ux, uy, uz)
    pos.setXYZ(i, ux * (1 + relief), uy * (1 + relief), uz * (1 + relief))
    const mare = fbm(ux * 1.4 + 40, uy * 1.4, uz * 1.4) // broad dark maria vs bright highlands
    let v = 0.5 + (mare - 0.5) * 0.32 + (fbm(ux * 18, uy * 18, uz * 18, 3) - 0.5) * 0.12
    v += crater < 0 ? crater * 4 : crater * 6 // darker floors, brighter rims
    v = Math.min(0.86, Math.max(0.22, v))
    col[i * 3] = v * 1.0; col[i * 3 + 1] = v * 0.985; col[i * 3 + 2] = v * 0.95
  }
  g.setAttribute('color', new THREE.BufferAttribute(col, 3))
  g.computeVertexNormals()
  return g
}

/** Procedural Earth texture (ocean, continents, clouds) on a canvas. */
export function makeEarthTexture(w = 512, h = 256) {
  const c = document.createElement('canvas'); c.width = w; c.height = h
  const ctx = c.getContext('2d'), img = ctx.createImageData(w, h)
  for (let j = 0; j < h; j++) {
    for (let i = 0; i < w; i++) {
      const u = (i / w) * Math.PI * 2, v = (j / h) * Math.PI
      const x = Math.sin(v) * Math.cos(u), y = Math.cos(v), z = Math.sin(v) * Math.sin(u)
      const land = fbm(x * 2.2 + 5, y * 2.2, z * 2.2, 5)
      const cloud = fbm(x * 4 + 90, y * 4, z * 4, 4)
      let r, g, b
      if (land > 0.53) { r = 70 + land * 70; g = 110 + land * 55; b = 60 + land * 20 } else { r = 20; g = 70 + land * 60; b = 150 + land * 70 }
      if (Math.abs(y) > 0.86) { r = g = b = 235 } // polar ice
      const k = Math.max(0, cloud - 0.55) * 3.2
      r += (255 - r) * k; g += (255 - g) * k; b += (255 - b) * k
      const o = (j * w + i) * 4
      img.data[o] = r; img.data[o + 1] = g; img.data[o + 2] = b; img.data[o + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace
  return t
}

/** Radial glow sprite texture (Sun corona, Earth atmosphere). */
export function makeGlowTexture(inner = 'rgba(255,214,120,1)', mid = 'rgba(255,160,40,0.35)') {
  const c = document.createElement('canvas'); c.width = c.height = 256
  const ctx = c.getContext('2d'), g = ctx.createRadialGradient(128, 128, 0, 128, 128, 128)
  g.addColorStop(0, inner); g.addColorStop(0.25, mid); g.addColorStop(1, 'rgba(255,140,0,0)')
  ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 256)
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace
  return t
}
