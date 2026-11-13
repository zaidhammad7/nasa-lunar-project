import { Suspense, useEffect, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import MoonSphere from './MoonSphere.jsx'
import CelestialBodies, { SkyClock } from './CelestialBodies.jsx'
import VectorsOverlay from './VectorsOverlay.jsx'
import CameraPill from '../controls/CameraPill.jsx'
import { sky } from './sky.js'
import { latLonToVec } from '../../lib/physics.js'
import { perfFlag } from '../../lib/perf.js'

const BASE_FOV = 42
const DEG = 180 / Math.PI

/** Smooth fly-to: frame-interpolated camera position, orbit target and field of view; any user drag cancels it. */
function CameraRig({ fly, controlsRef }) {
  const three = useThree()
  const { camera } = three
  useEffect(() => { if (import.meta.env.DEV) window.__r3f = three }, [three]) // dev-only handle for browser tests (stripped from production builds)
  const goal = useRef({ active: false, pos: new THREE.Vector3(), target: new THREE.Vector3(), fov: BASE_FOV })

  useEffect(() => {
    if (!fly || !fly.id) return
    const g = goal.current
    g.fov = BASE_FOV
    if (fly.kind === 'site' && fly.lat != null) {
      const v = new THREE.Vector3(...latLonToVec(fly.lat, fly.lon))
      g.pos.copy(v).multiplyScalar(1.5).add(new THREE.Vector3(0, 0, 0.2))
      g.target.copy(v).multiplyScalar(0.97)
    } else if (fly.kind === 'sunearth') {
      // At true scale the Sun and Earth are far away: look out from the Moon's neighbourhood along the Sun/Earth bisector
      const s = new THREE.Vector3(...sky.sun), e = new THREE.Vector3(...sky.earth)
      const sep = Math.acos(THREE.MathUtils.clamp(s.dot(e), -1, 1)) * DEG
      const aim = sep > 170 ? s.clone() : s.clone().add(e).normalize()
      let side = new THREE.Vector3().crossVectors(aim, new THREE.Vector3(0, 0, 1))
      if (side.lengthSq() < 1e-4) side = new THREE.Vector3(1, 0, 0)
      side.normalize()
      g.pos.copy(aim).multiplyScalar(-3.5).addScaledVector(side, 1.9).add(new THREE.Vector3(0, 0, 0.9))
      g.target.copy(g.pos).addScaledVector(aim, 8)
      g.fov = sep < 30 ? 58 : 88 // widen so both bodies fit when they are far apart in the sky
    } else { // south-pole view
      g.pos.set(0, -2.3, 0.95)
      g.target.set(0, -0.92, 0)
    }
    g.active = true
  }, [fly])

  useFrame((_, dt) => {
    const g = goal.current, c = controlsRef.current
    if (!g.active || !c) return
    const k = 1 - Math.exp(-dt * 3.4)
    camera.position.lerp(g.pos, k)
    c.target.lerp(g.target, k)
    if (Math.abs(camera.fov - g.fov) > 0.05) { camera.fov += (g.fov - camera.fov) * k; camera.updateProjectionMatrix() }
    c.update()
    if (camera.position.distanceTo(g.pos) < 0.012 && c.target.distanceTo(g.target) < 0.012 && Math.abs(camera.fov - g.fov) < 0.2) g.active = false
  })

  return <OrbitControls ref={controlsRef} makeDefault enableDamping dampingFactor={0.08} minDistance={1.04} maxDistance={4000}
    rotateSpeed={0.7} zoomSpeed={0.9} onStart={() => { goal.current.active = false }} />
}

function Scene({ sites, showPresets, pins, rays, fly, onPick }) {
  const controlsRef = useRef()
  return (
    <>
      <SkyClock />
      <color attach="background" args={['#070b14']} />
      <CelestialBodies />
      <MoonSphere sites={sites} showPresets={showPresets} pins={pins} onPick={onPick} />
      {!perfFlag('nolines') && <VectorsOverlay rays={rays} />}
      <CameraRig fly={fly} controlsRef={controlsRef} />
    </>
  )
}

/** The 3-D viewport at true astronomical scale: a logarithmic depth buffer keeps the Moon (r = 1) and the Sun (86,105 units away) artefact-free. */
export default function LunarViewport({ sites, showPresets, pins, rays, fly, onPick, onPreset, activePreset }) {
  return (
    <div className="relative h-full w-full">
      <Canvas shadows={!perfFlag('noshadow')} dpr={perfFlag('lowres') ? 1 : [1, 2]}
        gl={{ logarithmicDepthBuffer: true, antialias: true, powerPreference: 'high-performance' }}
        camera={{ position: [0, -2.8, 2.2], up: [0, 0, 1], fov: BASE_FOV, near: 0.01, far: 200000 }} style={{ cursor: 'crosshair' }}>
        <Suspense fallback={null}>
          <Scene sites={sites} showPresets={showPresets} pins={pins} rays={rays} fly={fly} onPick={onPick} />
        </Suspense>
      </Canvas>
      <CameraPill active={activePreset} onPreset={onPreset} />
    </div>
  )
}
