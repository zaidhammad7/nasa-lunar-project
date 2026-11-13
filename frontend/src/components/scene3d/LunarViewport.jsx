import { Suspense, useEffect, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import * as THREE from 'three'
import MoonSphere from './MoonSphere.jsx'
import CelestialBodies, { SkyClock } from './CelestialBodies.jsx'
import VectorsOverlay from './VectorsOverlay.jsx'
import { sky } from './sky.js'
import { latLonToVec } from '../../lib/physics.js'
import { cx, STATUS } from '../../lib/format.js'
import { perfFlag } from '../../lib/perf.js'

/** Smooth fly-to: frame-interpolated camera + orbit target (lerp inside useFrame); any user drag cancels it. */
function CameraRig({ fly, controlsRef }) {
  const { camera } = useThree()
  const goal = useRef({ active: false, pos: new THREE.Vector3(), target: new THREE.Vector3() })

  useEffect(() => {
    if (!fly || !fly.id) return
    const g = goal.current
    if (fly.kind === 'site' && fly.lat != null) {
      const v = new THREE.Vector3(...latLonToVec(fly.lat, fly.lon))
      g.pos.copy(v).multiplyScalar(1.5).add(new THREE.Vector3(0, 0, 0.2))
      g.target.copy(v).multiplyScalar(0.97)
    } else if (fly.kind === 'sunearth') {
      const s = new THREE.Vector3(...sky.sun), e = new THREE.Vector3(...sky.earth)
      let n = new THREE.Vector3().crossVectors(s, e)
      if (n.lengthSq() < 1e-4) n = new THREE.Vector3(0, 0, 1).cross(s)
      n.normalize()
      if (n.z < 0) n.negate() // keep the camera on the +Z (up) side so the scene is not upside-down
      g.pos.copy(n).multiplyScalar(6.4).add(new THREE.Vector3(0, 0, 0.4))
      g.target.set(0, 0, 0)
    } else { // south-pole overview
      g.pos.set(0, -2.35, 0.95)
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
    c.update()
    if (camera.position.distanceTo(g.pos) < 0.012 && c.target.distanceTo(g.target) < 0.012) g.active = false
  })

  return <OrbitControls ref={controlsRef} makeDefault enableDamping dampingFactor={0.08} minDistance={1.1} maxDistance={16}
    rotateSpeed={0.7} zoomSpeed={0.8} onStart={() => { goal.current.active = false }} />
}

function Scene({ sites, pins, rays, fly, onPick, onSelectSite, onHover }) {
  const controlsRef = useRef()
  return (
    <>
      <SkyClock />
      <color attach="background" args={['#0b1120']} />
      {!perfFlag('nostars') && <Stars radius={60} depth={30} count={2500} factor={3} saturation={0} fade speed={0.3} />}
      <CelestialBodies />
      <MoonSphere sites={sites} pins={pins} onPick={onPick} onSelectSite={onSelectSite} onHover={onHover} />
      {!perfFlag('nolines') && <VectorsOverlay rays={rays} />}
      <CameraRig fly={fly} controlsRef={controlsRef} />
    </>
  )
}

const PRESETS = [
  { kind: 'overview', label: 'South Pole Overview' },
  { kind: 'site', label: 'Site Close-Up' },
  { kind: 'sunearth', label: 'Sun / Earth Alignment' },
]

export default function LunarViewport({ sites, pins, rays, fly, onPick, onSelectSite, onPreset, activePreset }) {
  const [hover, setHover] = useState(null)
  return (
    <div className="relative h-full w-full">
      <Canvas shadows={!perfFlag('noshadow')} dpr={perfFlag('lowres') ? 1 : [1, 2]} camera={{ position: [0, -5.6, 2.4], up: [0, 0, 1], fov: 46, near: 0.03, far: 90 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }} style={{ cursor: hover ? 'crosshair' : 'grab' }}>
        <Suspense fallback={null}>
          <Scene sites={sites} pins={pins} rays={rays} fly={fly} onPick={onPick} onSelectSite={onSelectSite} onHover={setHover} />
        </Suspense>
      </Canvas>

      {/* camera presets */}
      <div className="glass absolute left-3 top-3 flex flex-col gap-1 rounded-lg border border-line p-1.5">
        {PRESETS.map((p) => (
          <button key={p.kind} onClick={() => onPreset(p.kind)}
            className={cx('rounded px-2.5 py-1 text-left text-[11px] font-medium transition-colors', activePreset === p.kind ? 'bg-earth/20 text-earth' : 'text-mute hover:bg-panel2 hover:text-ink')}>
            {p.label}
          </button>
        ))}
      </div>

      {/* legend */}
      <div className="glass absolute bottom-3 left-3 rounded-lg border border-line px-3 py-2 text-[11px]">
        <div className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          {['Optimal', 'Acceptable', 'Hazardous'].map((k) => (
            <span key={k} className="flex items-center gap-1.5 text-mute"><i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS[k].hex }} />{k}</span>
          ))}
          <span className="flex items-center gap-1.5 text-mute"><i className="inline-block h-0.5 w-4 bg-solar" />Solar ray</span>
          <span className="flex items-center gap-1.5 text-mute"><i className="inline-block h-0.5 w-4 bg-earth" />Earth LOS</span>
        </div>
        <div className="num text-mute">
          {hover ? <>cursor <span className="text-ink">{hover.lat.toFixed(3)}°</span>, <span className="text-ink">{hover.lon.toFixed(3)}°E</span>{hover.lat > -85 ? <span className="text-solar"> · outside −85…−90° study cap</span> : <span className="text-go"> · click to evaluate</span>}</> : 'Click the Moon surface to pick coordinates · drag to orbit · scroll to zoom · Sun/Earth distances not to scale'}
        </div>
      </div>
    </div>
  )
}
