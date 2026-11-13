import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { sky } from './sky.js'
import { surfacePoint } from './MoonSphere.jsx'
import { mastDrawHeight } from '../../lib/physics.js'

const RAY_LENGTH = 2.3
const Y = new THREE.Vector3(0, 1, 0)

/**
 * Golden solar ray + cyan (clear) / red (blocked) Earth line-of-sight from the mast tip.
 * Rays are two static unit cylinders that are only moved / rotated / scaled each frame (no geometry rebuilds, so no
 * GPU buffer churn); directions come from the shared sky state and the styling from `getLive()`.
 */
function Rays({ lat, lon, tower, getLive }) {
  const sunRef = useRef(), earthRef = useRef()
  const geom = useMemo(() => { const g = new THREE.CylinderGeometry(1, 1, 1, 8, 1, true); g.translate(0, 0.5, 0); return g }, [])
  const base = useMemo(() => surfacePoint(lat, lon, mastDrawHeight(tower) + 0.01), [lat, lon, tower]) // mast tip
  const tmp = useMemo(() => new THREE.Vector3(), [])
  useFrame(({ camera }) => {
    const live = getLive()
    const r = Math.min(0.012, Math.max(0.0012, (camera.position.length() - 1) * 0.0028))
    const place = (mesh, dir) => {
      if (!mesh) return
      tmp.set(dir[0], dir[1], dir[2])
      mesh.position.set(base[0], base[1], base[2])
      mesh.quaternion.setFromUnitVectors(Y, tmp)
      mesh.scale.set(r, RAY_LENGTH, r)
    }
    place(sunRef.current, sky.sun)
    place(earthRef.current, sky.earth)
    if (sunRef.current) sunRef.current.material.opacity = live.lit ? 0.95 : 0.22
    if (earthRef.current) {
      earthRef.current.material.color.set(live.connected ? '#38bdf8' : '#f43f5e')
      earthRef.current.material.opacity = live.connected ? 0.95 : 0.75
    }
  })
  return (
    <>
      <mesh ref={sunRef} geometry={geom} renderOrder={5}><meshBasicMaterial color="#fbbf24" transparent toneMapped={false} depthWrite={false} /></mesh>
      <mesh ref={earthRef} geometry={geom} renderOrder={5}><meshBasicMaterial color="#38bdf8" transparent toneMapped={false} depthWrite={false} /></mesh>
    </>
  )
}

export default function VectorsOverlay({ rays }) {
  return <>{rays.map(({ key, ...r }) => <Rays key={key} {...r} />)}</>
}
