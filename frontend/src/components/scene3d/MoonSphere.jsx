import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import TextSprite from './TextSprite.jsx'
import * as THREE from 'three'
import { buildMoonGeometry, reliefAt } from './moonRelief.js'
import { latLonToVec, vecToLatLon } from '../../lib/physics.js'
import { classHex } from '../../lib/format.js'
import { sky } from './sky.js'
import { perfFlag } from '../../lib/perf.js'

/** Point on the (relief-displaced) Moon surface for a selenographic coordinate, optionally lifted. */
export const surfacePoint = (lat, lon, lift = 0) => {
  const v = latLonToVec(lat, lon)
  const { relief } = reliefAt(v[0], v[1], v[2])
  return v.map((c) => c * (1 + relief + lift))
}

function SitePin({ lat, lon, color, label, tower, tilt }) {
  const grp = useRef()
  const { camera } = useThree()
  const pos = useMemo(() => surfacePoint(lat, lon, 0.002), [lat, lon])
  const quat = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(...latLonToVec(lat, lon))), [lat, lon])
  const ring = useRef()
  const H = 0.035 + tower * 0.0045 // exaggerated mast height (the real 1-20 m is invisible at Moon scale)
  useFrame(({ clock }) => {
    if (ring.current) ring.current.scale.setScalar(1 + 0.3 * Math.sin(clock.elapsedTime * 3.2))
    // keep the pin legible from the wide shot down to the close-up
    if (grp.current) grp.current.scale.setScalar(Math.min(1.7, Math.max(0.2, (camera.position.length() - 1) / 1.5)))
  })
  return (
    <group ref={grp} position={pos} quaternion={quat}>
      <mesh>
        <sphereGeometry args={[0.014, 16, 16]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
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
      <TextSprite text={label} color={color} position={[0, H + 0.05, 0]} height={0.03} />
    </group>
  )
}

/** Day/night boundary: a static great-circle torus, re-oriented (not rebuilt) every frame to stay perpendicular to the Sun. */
function Terminator() {
  const ref = useRef()
  const z = useMemo(() => new THREE.Vector3(0, 0, 1), [])
  const s = useMemo(() => new THREE.Vector3(), [])
  useFrame(() => {
    if (!ref.current) return
    s.set(sky.sun[0], sky.sun[1], sky.sun[2])
    ref.current.quaternion.setFromUnitVectors(z, s)
  })
  return (
    <mesh ref={ref} renderOrder={4}>
      <torusGeometry args={[1.012, 0.0032, 6, 200]} />
      <meshBasicMaterial color="#fbbf24" transparent opacity={0.55} toneMapped={false} depthWrite={false} />
    </mesh>
  )
}

/** The Moon: displaced mesh, invisible pick sphere (raycast -> lat/lon), 100 instanced site markers, Site A/B pins. */
export default function MoonSphere({ sites, pins, onPick, onSelectSite, onHover }) {
  const geometry = useMemo(() => buildMoonGeometry(52), [])
  const inst = useRef()
  const lastHover = useRef(0)

  const markerScale = useRef(0)
  const paint = (k) => {
    const m = new THREE.Matrix4(), c = new THREE.Color(), q = new THREE.Quaternion()
    sites.forEach((s, i) => {
      const p = surfacePoint(s.lat, s.lon, 0.004), r = k * (s.passes ? 1 : 0.62)
      m.compose(new THREE.Vector3(...p), q, new THREE.Vector3(r, r, r))
      inst.current.setMatrixAt(i, m)
      c.set(classHex(s.displayClass))
      if (!s.passes) c.multiplyScalar(0.4)
      inst.current.setColorAt(i, c)
    })
    inst.current.instanceMatrix.needsUpdate = true
    if (inst.current.instanceColor) inst.current.instanceColor.needsUpdate = true
    markerScale.current = k
  }
  useEffect(() => { paint(markerScale.current || 0.009) }, [sites]) // eslint-disable-line react-hooks/exhaustive-deps
  // constant ~5 px markers: world size follows the camera's distance to the surface
  const { camera } = useThree()
  useFrame(() => {
    if (!inst.current) return
    const k = Math.min(0.024, Math.max(0.0035, (camera.position.length() - 1) * 0.0068))
    if (Math.abs(k - markerScale.current) / markerScale.current > 0.07) paint(k)
  })

  const pointer = (e, fn) => {
    const { lat, lon } = vecToLatLon(e.point.x, e.point.y, e.point.z)
    fn(lat, lon)
  }

  return (
    <group>
      <mesh geometry={geometry} castShadow receiveShadow>
        <meshStandardMaterial vertexColors roughness={0.96} metalness={0} />
      </mesh>

      {/* invisible unit sphere: exact ray -> (lat, lon); clicks that were really drags (orbit) are ignored */}
      <mesh
        onClick={(e) => { if (e.delta > 5) return; e.stopPropagation(); pointer(e, onPick) }}
        onPointerMove={(e) => { const now = performance.now(); if (now - lastHover.current > 60) { lastHover.current = now; pointer(e, (la, lo) => onHover({ lat: la, lon: lo })) } }}
        onPointerOut={() => onHover(null)}
      >
        <sphereGeometry args={[1.0, 64, 48]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      <instancedMesh ref={inst} args={[null, null, sites.length]} frustumCulled={false}
        onClick={(e) => { if (e.delta > 5) return; e.stopPropagation(); const s = sites[e.instanceId]; if (s) onSelectSite(s.id) }}>
        <sphereGeometry args={[1, 10, 10]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>

      {!perfFlag('nolines') && <Terminator />}
      {pins.map(({ key, ...p }) => <SitePin key={key} {...p} />)}
    </group>
  )
}
