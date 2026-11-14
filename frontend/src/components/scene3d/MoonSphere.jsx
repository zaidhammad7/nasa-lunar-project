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

const UP = new THREE.Vector3(0, 1, 0)
const PAD_R = 0.016                         // landing-pad radius (scene units; exaggerated like the mast)
const PAD_LIFT = (PAD_R * PAD_R) / 2 + 0.0004 // sagitta of the pad over the unit sphere + margin: the flat pad never cuts the curved surface
const LEG_SPREAD = 0.012, LEG_TOP = 0.02    // tripod footprint radius and attachment height
const RINGS = 6                              // stiffening rings drawn along the mast
const BEACON_Y = 0.0145                      // beacon height above the mast top (local units)
/** On-screen legibility scale of the site model for a camera (shared with the Sun / Earth rays so they leave the beacon). */
export const pinScale = (camera) => Math.min(1.7, Math.max(0.32, (camera.position.length() - 1) / 1.5))
/** Height of the beacon above the surface in unscaled local units for a tower height (m). */
export const beaconLift = (tower) => PAD_LIFT + mastDrawHeight(tower) + BEACON_Y

/** A thin cylinder between two points (local frame), used for the tripod legs. */
function strut(a, b) {
  const va = new THREE.Vector3(...a), vb = new THREE.Vector3(...b), d = vb.clone().sub(va)
  return { pos: va.clone().add(vb).multiplyScalar(0.5).toArray(), len: d.length(), quat: new THREE.Quaternion().setFromUnitVectors(UP, d.normalize()) }
}

/**
 * Selected landing site with a scale-model solar mast, built in the site's local frame (+Y = surface normal, so it stands
 * exactly perpendicular to the Moon's curvature). The drawn mast height follows the tower setting smoothly (exaggerated so a
 * 1-150 m mast is visible at Moon scale; see mastDrawHeight), the pad is lifted by its sagitta so it never clips the sphere,
 * and the solar wings tilt with the panel-tilt control.
 */
function SitePin({ lat, lon, color, label, tower, tilt }) {
  const grp = useRef(), ring = useRef(), mast = useRef(), top = useRef(), beacon = useRef(), rings = useRef([])
  const { camera } = useThree()
  const pos = useMemo(() => surfacePoint(lat, lon, 0), [lat, lon])
  const quat = useMemo(() => new THREE.Quaternion().setFromUnitVectors(UP, new THREE.Vector3(...latLonToVec(lat, lon))), [lat, lon])
  const target = mastDrawHeight(tower)
  const h = useRef(target)
  const mastGeom = useMemo(() => { const g = new THREE.CylinderGeometry(0.0015, 0.0024, 1, 14, 1); g.translate(0, 0.5, 0); return g }, [])
  const legs = useMemo(() => [0, 120, 240].map((a) => {
    const r = (a * Math.PI) / 180
    return strut([LEG_SPREAD * Math.cos(r), PAD_LIFT, LEG_SPREAD * Math.sin(r)], [0, PAD_LIFT + LEG_TOP, 0])
  }), [])
  useEffect(() => () => mastGeom.dispose(), [mastGeom])
  const tiltRad = -(tilt * Math.PI) / 180

  useFrame(({ clock }, dt) => {
    h.current += (target - h.current) * (1 - Math.exp(-dt * 6)) // smooth grow / shrink when the tower height changes
    const hh = h.current
    if (mast.current) mast.current.scale.y = hh
    if (top.current) top.current.position.y = PAD_LIFT + hh
    rings.current.forEach((m, k) => { if (m) m.position.y = PAD_LIFT + LEG_TOP + ((hh - LEG_TOP) * (k + 1)) / (RINGS + 1) })
    const t = clock.elapsedTime
    if (ring.current) { const s = 1 + 0.35 * ((t * 0.8) % 1); ring.current.scale.setScalar(s); ring.current.material.opacity = 0.75 * (1 - ((t * 0.8) % 1)) }
    if (beacon.current) beacon.current.material.emissiveIntensity = 1.2 + Math.sin(t * 4) * 0.8
    if (grp.current) grp.current.scale.setScalar(pinScale(camera)) // legible at any zoom; prominent in close-up
  })

  const metal = <meshStandardMaterial color="#d6dde6" metalness={0.75} roughness={0.28} />
  return (
    <group ref={grp} position={pos} quaternion={quat}>
      {/* landing pad + selection glow (flat discs just above the curved surface: no z-fighting, no clipping) */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, PAD_LIFT * 0.5, 0]} renderOrder={3}>
        <circleGeometry args={[0.03, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.18} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, PAD_LIFT * 0.6, 0]} renderOrder={3}>
        <ringGeometry args={[0.028, 0.032, 64]} />
        <meshBasicMaterial color={color} transparent opacity={0.75} side={THREE.DoubleSide} depthWrite={false} toneMapped={false} blending={THREE.AdditiveBlending} />
      </mesh>
      <mesh position={[0, PAD_LIFT, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[PAD_R, PAD_R * 1.08, 0.0016, 32]} />
        <meshStandardMaterial color="#64748b" metalness={0.5} roughness={0.55} />
      </mesh>
      {/* tripod */}
      {legs.map((l, k) => (
        <mesh key={k} position={l.pos} quaternion={l.quat} castShadow>
          <cylinderGeometry args={[0.0008, 0.0011, l.len, 8]} />
          {metal}
        </mesh>
      ))}
      {/* mast (unit-height geometry scaled to the animated height) + stiffening rings */}
      <mesh ref={mast} geometry={mastGeom} position={[0, PAD_LIFT, 0]} castShadow>{metal}</mesh>
      {Array.from({ length: RINGS }, (_, k) => (
        <mesh key={k} ref={(m) => { rings.current[k] = m }} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.0028, 0.0005, 6, 20]} />
          {metal}
        </mesh>
      ))}
      {/* top: hub, two solar wings at the real panel tilt, antenna + beacon */}
      <group ref={top}>
        <mesh castShadow><boxGeometry args={[0.008, 0.004, 0.008]} />{metal}</mesh>
        {[-1, 1].map((side) => (
          <group key={side} position={[side * 0.024, 0, 0]} rotation={[tiltRad, 0, 0]}>
            <mesh castShadow><boxGeometry args={[0.038, 0.0018, 0.026]} /><meshStandardMaterial color="#c9a227" metalness={0.8} roughness={0.3} /></mesh>
            <mesh position={[0, 0.0011, 0]}><boxGeometry args={[0.035, 0.0006, 0.023]} /><meshStandardMaterial color="#1e3a8a" emissive="#1d4ed8" emissiveIntensity={0.35} metalness={0.4} roughness={0.25} /></mesh>
          </group>
        ))}
        <mesh position={[0, 0.008, 0]}><cylinderGeometry args={[0.0006, 0.0006, 0.012, 6]} />{metal}</mesh>
        <mesh ref={beacon} position={[0, BEACON_Y, 0]}><sphereGeometry args={[0.0024, 16, 12]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.5} toneMapped={false} /></mesh>
        <TextSprite text={label} color={color} position={[0, 0.042, 0]} height={0.021} />
      </group>
    </group>
  )
}

/** Day/night boundary: a static great-circle torus re-oriented (not rebuilt) every frame to stay perpendicular to the Sun. */
function Terminator() {
  const ref = useRef(), tube = useRef()
  const z = useMemo(() => new THREE.Vector3(0, 0, 1), [])
  const s = useMemo(() => new THREE.Vector3(), [])
  // 1-px great circle (crisp at any zoom) + a soft tube that is shown only from afar, where 1 px would be too faint
  const circle = useMemo(() => {
    const pts = []
    for (let i = 0; i < 720; i++) { const a = (i / 720) * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a) * 1.0012, Math.sin(a) * 1.0012, 0)) }
    return new THREE.BufferGeometry().setFromPoints(pts)
  }, [])
  useEffect(() => () => circle.dispose(), [circle])
  useFrame(({ camera }) => {
    if (!ref.current) return
    s.set(sky.sun[0], sky.sun[1], sky.sun[2])
    ref.current.quaternion.setFromUnitVectors(z, s)
    if (tube.current) tube.current.visible = camera.position.length() > 1.6
  })
  return (
    <group ref={ref}>
      <lineLoop geometry={circle} renderOrder={4}>
        <lineBasicMaterial color="#fbbf24" transparent opacity={0.85} toneMapped={false} depthWrite={false} />
      </lineLoop>
      <mesh ref={tube} renderOrder={4}>
        <torusGeometry args={[1.004, 0.0028, 6, 200]} />
        <meshBasicMaterial color="#fbbf24" transparent opacity={0.5} toneMapped={false} depthWrite={false} />
      </mesh>
    </group>
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
      const r = k * (s.passes ? 1 : 0.62), p = surfacePoint(s.lat, s.lon, r * 0.75 + 0.0004) // lifted by its radius: never sinks into the curved surface
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
    const k = Math.min(0.016, Math.max(0.0006, (camera.position.length() - 1) * 0.0046)) // ~constant on-screen size, small up close
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
        <sphereGeometry args={[1, 16, 12]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>

      <Terminator />
      {pins.map(({ key, ...p }) => <SitePin key={key} {...p} />)}
    </group>
  )
}
