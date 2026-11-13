import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import TextSprite from './TextSprite.jsx'
import { useMoonTextures } from './textures.js'
import { latLonToVec, mastDrawHeight } from '../../lib/physics.js'
import { classHex } from '../../lib/format.js'
import { sky } from './sky.js'

/** Point on the Moon's surface (unit sphere) for a selenographic coordinate, optionally lifted. */
export const surfacePoint = (lat, lon, lift = 0) => latLonToVec(lat, lon, 1 + lift)

const CLICK_SLOP_PX = 4 // pointer travel (px) below which a press/release counts as a click, not an OrbitControls drag

function SitePin({ lat, lon, color, label, tower, tilt }) {
  const grp = useRef(), ring = useRef()
  const { camera } = useThree()
  const pos = useMemo(() => surfacePoint(lat, lon, 0.001), [lat, lon])
  const quat = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(...latLonToVec(lat, lon))), [lat, lon])
  const H = mastDrawHeight(tower) // exaggerated mast height (real masts are invisible at Moon scale)
  useFrame(({ clock }) => {
    if (ring.current) ring.current.scale.setScalar(1 + 0.3 * Math.sin(clock.elapsedTime * 3.2))
    if (grp.current) grp.current.scale.setScalar(Math.min(1.7, Math.max(0.2, (camera.position.length() - 1) / 1.5))) // stay legible at any zoom
  })
  return (
    <group ref={grp} position={pos} quaternion={quat}>
      <mesh><sphereGeometry args={[0.014, 16, 16]} /><meshBasicMaterial color={color} toneMapped={false} /></mesh>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.003, 0]}>
        <ringGeometry args={[0.032, 0.041, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.8} side={THREE.DoubleSide} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      <mesh position={[0, H / 2, 0]} castShadow>
        <cylinderGeometry args={[0.0032, 0.0042, H, 10]} />
        <meshStandardMaterial color="#cbd5e1" metalness={0.6} roughness={0.35} />
      </mesh>
      <mesh position={[0, H, 0]} rotation={[0, 0, -(tilt * Math.PI) / 180]} castShadow>
        <boxGeometry args={[0.075, 0.004, 0.045]} />
        <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={0.55} />
      </mesh>
      <TextSprite text={label} color={color} position={[0, H + 0.05, 0]} height={0.016} />
    </group>
  )
}

/** Day/night boundary: a static great-circle torus re-oriented (not rebuilt) every frame to stay perpendicular to the Sun. */
function Terminator() {
  const ref = useRef()
  const z = useMemo(() => new THREE.Vector3(0, 0, 1), [])
  const s = useMemo(() => new THREE.Vector3(), [])
  useFrame(() => { if (ref.current) { s.set(sky.sun[0], sky.sun[1], sky.sun[2]); ref.current.quaternion.setFromUnitVectors(z, s) } })
  return (
    <mesh ref={ref} renderOrder={4}>
      <torusGeometry args={[1.004, 0.0028, 6, 200]} />
      <meshBasicMaterial color="#fbbf24" transparent opacity={0.5} toneMapped={false} depthWrite={false} />
    </mesh>
  )
}

/**
 * The Moon: 128x128 sphere, real LRO-derived albedo + bump (procedural fallback offline), matte regolith shading.
 * A click anywhere on the surface becomes an exact (lat, lon) - no snapping to the 100 presets.
 */
export default function MoonSphere({ sites, showPresets, pins, onPick }) {
  const moonRef = useRef(), inst = useRef(), down = useRef(null), scale = useRef(0)
  const tex = useMoonTextures()
  const { camera } = useThree()

  const paint = (k) => {
    if (!inst.current) return
    const m = new THREE.Matrix4(), c = new THREE.Color(), q = new THREE.Quaternion()
    sites.forEach((s, i) => {
      const p = surfacePoint(s.lat, s.lon, 0.002), r = k * (s.passes ? 1 : 0.62)
      m.compose(new THREE.Vector3(...p), q, new THREE.Vector3(r, r, r))
      inst.current.setMatrixAt(i, m)
      c.set(classHex(s.displayClass))
      if (!s.passes) c.multiplyScalar(0.4)
      inst.current.setColorAt(i, c)
    })
    inst.current.instanceMatrix.needsUpdate = true
    if (inst.current.instanceColor) inst.current.instanceColor.needsUpdate = true
    scale.current = k
  }
  useEffect(() => { paint(scale.current || 0.006) }, [sites]) // eslint-disable-line react-hooks/exhaustive-deps
  useFrame(() => { // small, constant ~4 px preset markers
    if (!showPresets || !inst.current) return
    const k = Math.min(0.016, Math.max(0.0022, (camera.position.length() - 1) * 0.0046))
    if (Math.abs(k - scale.current) / Math.max(scale.current, 1e-6) > 0.08) paint(k)
  })

  const hit = (e) => {
    // exact selenographic coordinates of the clicked surface point (Moon-local, +Y north, lon 0 at +X, east toward -Z)
    const p = moonRef.current.worldToLocal(e.point.clone()).normalize()
    const lat = Number((Math.atan2(p.y, Math.hypot(p.x, p.z)) * (180 / Math.PI)).toFixed(4)) // atan2: exact near the pole
    let lon = Number((Math.atan2(-p.z, p.x) * (180 / Math.PI)).toFixed(4))
    if (lon < 0) lon += 360
    onPick(lat, lon)
  }

  return (
    <group>
      <mesh ref={moonRef} castShadow receiveShadow
        onPointerDown={(e) => { down.current = [e.nativeEvent.clientX, e.nativeEvent.clientY] }}
        onClick={(e) => {
          const d = down.current
          if (!d || Math.hypot(e.nativeEvent.clientX - d[0], e.nativeEvent.clientY - d[1]) >= CLICK_SLOP_PX) return // it was a camera drag
          e.stopPropagation(); hit(e)
        }}>
        <sphereGeometry args={[1, 128, 128]} />
        <meshStandardMaterial map={tex.map} bumpMap={tex.bump} bumpScale={0.025} roughness={0.94} metalness={0} />
      </mesh>

      {/* preset markers are purely visual: they never intercept pointer events, so free surface clicking is never blocked */}
      <instancedMesh ref={inst} args={[null, null, sites.length]} frustumCulled={false} visible={showPresets} raycast={() => null}>
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>

      <Terminator />
      {pins.map(({ key, ...p }) => <SitePin key={key} {...p} />)}
    </group>
  )
}
