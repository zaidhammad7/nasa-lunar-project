import { useMemo } from 'react'
import * as THREE from 'three'

/**
 * Deep-space star field (6000 stars on a 50,000-unit sphere). Built on THREE.Points instead of drei's <Stars/> because that
 * component uses a custom shader without logarithmic-depth support, which mis-sorts against the log-depth Moon/Earth/Sun.
 * Drawn first in the opaque pass with depth testing off, so it is always the backdrop.
 */
export default function StarField({ count = 6000, radius = 50000 }) {
  const geo = useMemo(() => {
    const pos = new Float32Array(count * 3), col = new Float32Array(count * 3)
    let s = 7
    const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647 }
    for (let i = 0; i < count; i++) {
      const u = rnd() * 2 - 1, t = rnd() * Math.PI * 2, r = Math.sqrt(1 - u * u)
      pos.set([r * Math.cos(t) * radius, u * radius, r * Math.sin(t) * radius], i * 3)
      const b = 0.35 + Math.pow(rnd(), 3) * 0.65, tint = rnd()
      col.set([b * (0.85 + 0.15 * tint), b * 0.95, b * (1 - 0.15 * tint)], i * 3)
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    return g
  }, [count, radius])
  return (
    <points geometry={geo} renderOrder={-10} frustumCulled={false}>
      <pointsMaterial size={1.9} sizeAttenuation={false} vertexColors depthTest={false} depthWrite={false} toneMapped={false} fog={false} />
    </points>
  )
}
