import { useEffect, useMemo } from 'react'
import * as THREE from 'three'

/** Constant-screen-size text label (canvas texture on a sprite): no DOM, no per-frame layout work. */
export default function TextSprite({ text, color = '#f1f5f9', border = true, position = [0, 0, 0], height = 0.05, anchorTop = false }) {
  const { tex, aspect } = useMemo(() => {
    const c = document.createElement('canvas')
    const ctx = c.getContext('2d')
    const font = '600 30px "JetBrains Mono Variable", ui-monospace, monospace'
    ctx.font = font
    const w = Math.ceil(ctx.measureText(text).width) + 28, h = 48
    c.width = w; c.height = h
    ctx.font = font
    ctx.fillStyle = 'rgba(11,17,32,0.88)'
    ctx.beginPath(); ctx.roundRect(1, 1, w - 2, h - 2, 9); ctx.fill()
    if (border) { ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke() }
    ctx.fillStyle = color; ctx.textBaseline = 'middle'; ctx.fillText(text, 14, h / 2 + 1)
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace
    return { tex: t, aspect: w / h }
  }, [text, color, border])
  useEffect(() => () => tex.dispose(), [tex])
  return (
    <sprite raycast={() => null} position={position} scale={[height * aspect, height, 1]} renderOrder={10} center={anchorTop ? [0.5, 1.15] : [0.5, 0.5]}>
      <spriteMaterial map={tex} sizeAttenuation={false} depthTest={false} transparent toneMapped={false} />
    </sprite>
  )
}
