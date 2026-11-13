// Moon / Earth surface textures.
//   1. A fast low-res procedural placeholder is used for the very first frame (no blocking work, no network).
//   2. Real maps are fetched from CORS-enabled CDNs (three.js example textures, threex.planets bump map). The real 1k
//      lunar map is upscaled onto a 4096x2048 canvas and overlaid with procedural micro-craters so polar close-ups stay sharp.
//   3. If every URL fails (offline) a high-detail fully procedural crater canvas is used instead.
import * as THREE from 'three'
import { useEffect, useState } from 'react'

const TJS = 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/'
export const URLS = {
  moonAlbedo: [TJS + 'moon_1024.jpg', 'https://threejs.org/examples/textures/planets/moon_1024.jpg',
    'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/moonmap1k.jpg'],
  moonBump: ['https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/moonbump1k.jpg'],
  earthMap: [TJS + 'earth_atmos_2048.jpg'],
  earthClouds: [TJS + 'earth_clouds_1024.png'],
}

function loadImage(urls, timeoutMs = 9000) {
  return urls.reduce((p, url) => p.then((img) => img || new Promise((resolve) => {
    const im = new Image()
    im.crossOrigin = 'anonymous'
    const to = setTimeout(() => resolve(null), timeoutMs)
    im.onload = () => { clearTimeout(to); resolve(im) }
    im.onerror = () => { clearTimeout(to); resolve(null) }
    im.src = url
  })), Promise.resolve(null))
}

function mulberry32(seed) {
  let a = seed >>> 0
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296 }
}
const canvas = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c }

/** Soft craters on an equirectangular canvas. mode 'color' darkens floors / brightens rims; 'height' paints a relief map. */
function drawCraters(ctx, w, h, rnd, n, { minR, maxR, alpha, mode, polar = 0.35 }) {
  for (let i = 0; i < n; i++) {
    const south = rnd() < polar // extra, rugged south-polar craters (the mission area)
    const lat = south ? -90 + rnd() * rnd() * 22 : Math.asin(rnd() * 2 - 1) * (180 / Math.PI)
    const x = rnd() * w, y = ((90 - lat) / 180) * h
    const r = minR + Math.pow(rnd(), 2.6) * (maxR - minR)
    const stretch = Math.min(7, 1 / Math.max(Math.cos((lat * Math.PI) / 180), 0.14))
    for (const dx of x < r * stretch * 1.3 ? [0, w] : x > w - r * stretch * 1.3 ? [0, -w] : [0]) {
      ctx.save()
      ctx.translate(x + dx, y); ctx.scale(stretch, 1)
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r * 1.3)
      if (mode === 'color') {
        g.addColorStop(0, `rgba(30,30,30,${alpha * 0.55})`); g.addColorStop(0.7 / 1.3, `rgba(40,40,40,${alpha * 0.35})`)
        g.addColorStop(0.92 / 1.3, `rgba(235,235,230,${alpha * 0.55})`); g.addColorStop(1, 'rgba(200,200,195,0)')
      } else {
        g.addColorStop(0, `rgba(20,20,20,${alpha})`); g.addColorStop(0.72 / 1.3, `rgba(70,70,70,${alpha * 0.7})`)
        g.addColorStop(0.96 / 1.3, `rgba(255,255,255,${alpha})`); g.addColorStop(1, 'rgba(128,128,128,0)')
      }
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, r * 1.3, 0, Math.PI * 2); ctx.fill()
      ctx.restore()
    }
  }
}

function speckle(ctx, w, h, rnd, n, a) {
  for (let i = 0; i < n; i++) { const v = rnd() > 0.5 ? 255 : 0; ctx.fillStyle = `rgba(${v},${v},${v},${a * rnd()})`; ctx.fillRect(rnd() * w, rnd() * h, 1 + rnd() * 1.6, 1 + rnd() * 1.6) }
}

/** Fully procedural lunar map pair (colour + height) at the requested size. */
function proceduralMoon(w, h, craters) {
  const rnd = mulberry32(1969)
  const col = canvas(w, h), cc = col.getContext('2d')
  cc.fillStyle = '#8c8b88'; cc.fillRect(0, 0, w, h)
  for (let i = 0; i < 26; i++) { // dark maria / bright highlands
    const x = rnd() * w, y = h * (0.2 + rnd() * 0.6), r = w * (0.03 + rnd() * 0.07), g = cc.createRadialGradient(x, y, 0, x, y, r)
    g.addColorStop(0, 'rgba(55,55,58,0.45)'); g.addColorStop(1, 'rgba(55,55,58,0)'); cc.fillStyle = g; cc.fillRect(x - r, y - r, 2 * r, 2 * r)
  }
  const hgt = canvas(w, h), hc = hgt.getContext('2d')
  hc.fillStyle = '#808080'; hc.fillRect(0, 0, w, h)
  const s = w / 2048
  drawCraters(cc, w, h, mulberry32(7), craters, { minR: 2 * s, maxR: 55 * s, alpha: 0.5, mode: 'color' })
  drawCraters(hc, w, h, mulberry32(7), craters, { minR: 2 * s, maxR: 55 * s, alpha: 0.85, mode: 'height' })
  speckle(cc, w, h, rnd, Math.round(w * h / 60), 0.1); speckle(hc, w, h, rnd, Math.round(w * h / 60), 0.1)
  return { col, hgt }
}

function toTexture(c, srgb) {
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace
  t.anisotropy = 8
  t.wrapS = THREE.RepeatWrapping
  return t
}

/** Real 1k lunar maps -> 4096x2048 hybrid (upscaled real data + procedural micro-craters). */
function hybridMoon(albedo, bump) {
  const W = 4096, H = 2048, rnd = mulberry32(42)
  const col = canvas(W, H), cc = col.getContext('2d')
  cc.imageSmoothingEnabled = true; cc.imageSmoothingQuality = 'high'
  cc.drawImage(albedo, 0, 0, W, H)
  const detail = canvas(W, H), dc = detail.getContext('2d')
  dc.fillStyle = '#808080'; dc.fillRect(0, 0, W, H)
  drawCraters(dc, W, H, mulberry32(11), 4200, { minR: 2, maxR: 70, alpha: 0.9, mode: 'height', polar: 0.4 })
  speckle(dc, W, H, rnd, 140000, 0.12)
  cc.globalCompositeOperation = 'soft-light'; cc.globalAlpha = 0.55; cc.drawImage(detail, 0, 0); cc.globalAlpha = 1; cc.globalCompositeOperation = 'source-over'
  const hgt = canvas(W / 2, H / 2), hc = hgt.getContext('2d')
  hc.imageSmoothingQuality = 'high'
  if (bump) hc.drawImage(bump, 0, 0, W / 2, H / 2)
  else { hc.filter = 'grayscale(1) contrast(1.4)'; hc.drawImage(albedo, 0, 0, W / 2, H / 2); hc.filter = 'none' }
  hc.globalCompositeOperation = 'overlay'; hc.globalAlpha = 0.85; hc.drawImage(detail, 0, 0, W / 2, H / 2); hc.globalAlpha = 1; hc.globalCompositeOperation = 'source-over'
  return { col, hgt }
}

/** { map, bump, kind }: instant placeholder, then upgraded to real-data hybrid (or a detailed procedural map offline). */
export function useMoonTextures() {
  const [tex, setTex] = useState(() => { const p = proceduralMoon(1024, 512, 700); return { map: toTexture(p.col, true), bump: toTexture(p.hgt, false), kind: 'placeholder' } })
  useEffect(() => {
    let dead = false
    ;(async () => {
      const [alb, bmp] = await Promise.all([loadImage(URLS.moonAlbedo), loadImage(URLS.moonBump)])
      if (dead) return
      await new Promise((r) => setTimeout(r, 30)) // let the first frames paint before the heavy canvas work
      const m = alb ? hybridMoon(alb, bmp) : proceduralMoon(2048, 1024, 2600)
      if (dead) return
      setTex((old) => { old.map.dispose(); old.bump.dispose(); return { map: toTexture(m.col, true), bump: toTexture(m.hgt, false), kind: alb ? 'real+detail' : 'procedural' } })
    })()
    return () => { dead = true }
  }, [])
  return tex
}

function proceduralEarth(w, h) {
  const c = canvas(w, h), ctx = c.getContext('2d'), rnd = mulberry32(2026)
  const g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, '#1b4f8c'); g.addColorStop(0.5, '#1d6fb5'); g.addColorStop(1, '#1b4f8c')
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h)
  for (let i = 0; i < 70; i++) { // continents as blobs of ellipses
    const cx = rnd() * w, cy = h * (0.12 + rnd() * 0.76), n = 4 + Math.floor(rnd() * 8)
    ctx.fillStyle = rnd() > 0.35 ? `rgb(${60 + rnd() * 40},${110 + rnd() * 40},${55 + rnd() * 20})` : `rgb(${150 + rnd() * 40},${130 + rnd() * 30},${90})`
    for (let k = 0; k < n; k++) { ctx.beginPath(); ctx.ellipse(cx + (rnd() - 0.5) * w * 0.07, cy + (rnd() - 0.5) * h * 0.08, w * (0.01 + rnd() * 0.03), h * (0.01 + rnd() * 0.04), rnd() * 3, 0, Math.PI * 2); ctx.fill() }
  }
  ctx.fillStyle = '#eef3f8'; ctx.fillRect(0, 0, w, h * 0.06); ctx.fillRect(0, h * 0.94, w, h * 0.06)
  for (let i = 0; i < 90; i++) { ctx.fillStyle = `rgba(255,255,255,${0.12 + rnd() * 0.2})`; ctx.beginPath(); ctx.ellipse(rnd() * w, rnd() * h, w * (0.02 + rnd() * 0.06), h * (0.008 + rnd() * 0.02), rnd() * 3, 0, Math.PI * 2); ctx.fill() }
  return c
}

/** { map, clouds } for the Earth (real 2k day map + cloud layer; instant procedural placeholder). */
export function useEarthTextures() {
  const [tex, setTex] = useState(() => ({ map: toTexture(proceduralEarth(512, 256), true), clouds: null }))
  useEffect(() => {
    let dead = false
    ;(async () => {
      const [m, cl] = await Promise.all([loadImage(URLS.earthMap), loadImage(URLS.earthClouds)])
      if (dead) return
      setTex((old) => {
        const map = m ? toTexture((() => { const c = canvas(m.naturalWidth, m.naturalHeight); c.getContext('2d').drawImage(m, 0, 0); return c })(), true) : old.map
        let clouds = null
        if (cl) { clouds = new THREE.Texture(cl); clouds.colorSpace = THREE.SRGBColorSpace; clouds.needsUpdate = true }
        return { map, clouds }
      })
    })()
    return () => { dead = true }
  }, [])
  return tex
}
