import { Suspense, useEffect, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import MoonSphere, { beaconLift } from './MoonSphere.jsx'
import CelestialBodies, { SkyClock } from './CelestialBodies.jsx'
import VectorsOverlay from './VectorsOverlay.jsx'
import { HeatmapCap, CraterLabels } from './MapLayers.jsx'
import CameraPill from '../controls/CameraPill.jsx'
import { sky } from './sky.js'
import { latLonToVec } from '../../lib/physics.js'
import { perfFlag } from '../../lib/perf.js'

const BASE_FOV = 42
const MIN_CAMERA_RADIUS = 1.02 // scene units from the Moon's centre (~35 km above the surface)
// Wheel zoom: proportional to how far the wheel / trackpad actually moved, so a mouse notch (deltaY ~ 100) and a trackpad
// gesture (many small deltas) zoom by the same total amount. exp(100 * 0.0015) ~ 16% per mouse notch; eased, not jumped.
const ZOOM_PER_DELTA = 0.0015
const ZOOM_MAX_STEP = 300      // largest deltaY honoured per event (fast-scroll mice send huge spikes)
const ZOOM_EASE = 14           // 1/s: how quickly the camera reaches the requested distance
const MIN_DISTANCE = 0.05, MAX_DISTANCE = 4000
const DEG = 180 / Math.PI

/** Smooth fly-to: frame-interpolated camera position, orbit target and field of view; any user drag cancels it. */
function CameraRig({ fly, controlsRef }) {
  const three = useThree()
  const { camera } = three
  useEffect(() => { if (import.meta.env.DEV) window.__r3f = three }, [three]) // dev-only handle for browser tests (stripped from production builds)
  const goal = useRef({ active: false, pos: new THREE.Vector3(), target: new THREE.Vector3(), fov: BASE_FOV })
  // Orbit "up" axis: world +Z for the global views; the site's local vertical (surface normal) for the close-up, so the mast
  // stands upright on screen and its height reads in profile. OrbitControls fixes its up-axis when created -> remount on change.
  const [upKey, setUpKey] = useState('global')
  const zoomGoal = useRef(null) // requested camera-to-target distance (scene units), eased toward in useFrame
  const { gl } = three

  // Own wheel handler (capture phase, before OrbitControls), so zoom speed does not depend on the input device's event rate.
  useEffect(() => {
    const host = gl.domElement.parentElement
    if (!host) return undefined
    const onWheel = (e) => {
      const c = controlsRef.current
      if (!c) return
      e.preventDefault(); e.stopPropagation()
      const unit = e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 100 : 1 // lines (Firefox: 3 per notch) / pages -> ~pixels
      const dy = Math.max(-ZOOM_MAX_STEP, Math.min(ZOOM_MAX_STEP, e.deltaY * unit))
      const from = zoomGoal.current ?? camera.position.distanceTo(c.target)
      zoomGoal.current = Math.max(MIN_DISTANCE, Math.min(MAX_DISTANCE, from * Math.exp(dy * ZOOM_PER_DELTA)))
      goal.current.active = false // the user takes over from any camera fly-to
    }
    host.addEventListener('wheel', onWheel, { passive: false, capture: true })
    return () => host.removeEventListener('wheel', onWheel, { capture: true })
  }, [gl, camera, controlsRef])

  useEffect(() => {
    if (!fly || !fly.id) return
    const g = goal.current
    g.fov = BASE_FOV
    if (fly.kind === 'site' && fly.lat != null) { // selecting / clicking a site: overhead view, the Moon stays clickable
      camera.up.set(0, 0, 1)
      setUpKey('global')
      const v = new THREE.Vector3(...latLonToVec(fly.lat, fly.lon))
      g.pos.copy(v).multiplyScalar(1.5).add(new THREE.Vector3(0, 0, 0.2))
      g.target.copy(v).multiplyScalar(0.97)
      g.active = true
      return
    }
    if (fly.kind === 'tower' && fly.lat != null) {
      // "Pin Close-Up": oblique view a little above the surface, aimed at the middle of the mast, local vertical up
      const v = new THREE.Vector3(...latLonToVec(fly.lat, fly.lon)), n = v.clone().normalize()
      let side = new THREE.Vector3().crossVectors(n, new THREE.Vector3(0, 0, 1))
      if (side.lengthSq() < 1e-6) side = new THREE.Vector3(1, 0, 0)
      side.normalize()
      camera.up.copy(n)
      setUpKey(`site:${fly.id}`)
      // frame the whole drawn mast (close-up legibility scale 0.32): aim at mid-height, back off in proportion to its height
      const top = beaconLift(fly.tower ?? 5) * 0.32
      g.pos.copy(v).addScaledVector(n, Math.max(0.05, top * 0.6)).addScaledVector(side, Math.max(0.16, top * 2.6))
      g.target.copy(v).addScaledVector(n, top * 0.5)
      g.active = true
      return
    }
    camera.up.set(0, 0, 1)
    setUpKey('global')
    if (fly.kind === 'sunearth') {
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
    const c0 = controlsRef.current
    if (zoomGoal.current != null && c0) { // eased wheel zoom along the view direction
      const off = camera.position.clone().sub(c0.target)
      const d = off.length(), want = zoomGoal.current
      const next = d + (want - d) * (1 - Math.exp(-dt * ZOOM_EASE))
      camera.position.copy(c0.target).add(off.setLength(next))
      c0.update()
      if (Math.abs(next - want) / want < 0.002) zoomGoal.current = null
    }
    // keep the camera above the surface (OrbitControls' minDistance is measured from the target, not the Moon's centre)
    if (camera.position.length() < MIN_CAMERA_RADIUS) {
      camera.position.setLength(MIN_CAMERA_RADIUS)
      if (zoomGoal.current != null && controlsRef.current && zoomGoal.current < camera.position.distanceTo(controlsRef.current.target)) zoomGoal.current = null // reached the surface: stop asking for more
    }
    const g = goal.current, c = controlsRef.current
    if (!g.active || !c) return
    const k = 1 - Math.exp(-dt * 3.4)
    camera.position.lerp(g.pos, k)
    c.target.lerp(g.target, k)
    if (Math.abs(camera.fov - g.fov) > 0.05) { camera.fov += (g.fov - camera.fov) * k; camera.updateProjectionMatrix() }
    c.update()
    if (camera.position.distanceTo(g.pos) < 0.012 && c.target.distanceTo(g.target) < 0.012 && Math.abs(camera.fov - g.fov) < 0.2) g.active = false
  })

  return <OrbitControls key={upKey} ref={controlsRef} makeDefault enableDamping dampingFactor={0.08} minDistance={MIN_DISTANCE} maxDistance={MAX_DISTANCE}
    rotateSpeed={0.7} zoomSpeed={1} onStart={() => { goal.current.active = false; zoomGoal.current = null }} />
}

function Scene({ sites, showPresets, pins, rays, fly, onPick, heatSites, showCraters }) {
  const controlsRef = useRef()
  return (
    <>
      <SkyClock />
      <color attach="background" args={['#070b14']} />
      <CelestialBodies />
      <MoonSphere sites={sites} showPresets={showPresets} pins={pins} onPick={onPick} />
      {heatSites && <HeatmapCap sites={heatSites} />}
      {showCraters && <CraterLabels />}
      {!perfFlag('nolines') && <VectorsOverlay rays={rays} />}
      <CameraRig fly={fly} controlsRef={controlsRef} />
    </>
  )
}

/** The 3-D viewport at true astronomical scale: a logarithmic depth buffer keeps the Moon (r = 1) and the Sun (86,105 units away) artefact-free. */
export default function LunarViewport({ sites, showPresets, pins, rays, fly, onPick, onPreset, activePreset, heatSites, showCraters }) {
  return (
    <div className="relative h-full w-full">
      <Canvas shadows={!perfFlag('noshadow')} dpr={perfFlag('lowres') ? 1 : [1, 2]}
        gl={{ logarithmicDepthBuffer: true, antialias: true, powerPreference: 'high-performance' }}
        camera={{ position: [0, -2.8, 2.2], up: [0, 0, 1], fov: BASE_FOV, near: 0.01, far: 200000 }} style={{ cursor: 'crosshair' }}>
        <Suspense fallback={null}>
          <Scene sites={sites} showPresets={showPresets} pins={pins} rays={rays} fly={fly} onPick={onPick} heatSites={heatSites} showCraters={showCraters} />
        </Suspense>
      </Canvas>
      <CameraPill active={activePreset} onPreset={onPreset} />
    </div>
  )
}
