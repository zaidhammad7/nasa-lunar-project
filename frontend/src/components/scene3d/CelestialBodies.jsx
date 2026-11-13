import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import TextSprite from './TextSprite.jsx'
import * as THREE from 'three'
import { makeEarthTexture, makeGlowTexture } from './moonRelief.js'
import { sky, updateSky, SUN_DISTANCE, EARTH_DISTANCE } from './sky.js'

/** Advances the shared sky state from the mission clock once per frame (must be mounted before the bodies). */
export function SkyClock() {
  useFrame(() => updateSky())
  return null
}

/** 3-D Sun (corona glow + shadow-casting directional light) and 3-D Earth (moves with libration). */
export default function CelestialBodies() {
  const sunGroup = useRef(), earthGroup = useRef(), earthMesh = useRef(), light = useRef()
  const earthTex = useMemo(() => makeEarthTexture(), [])
  const corona = useMemo(() => makeGlowTexture('rgba(255,236,170,1)', 'rgba(255,170,50,0.38)'), [])
  const halo = useMemo(() => makeGlowTexture('rgba(125,211,252,0.9)', 'rgba(56,189,248,0.25)'), [])

  useFrame((_, dt) => {
    const [sx, sy, sz] = sky.sun, [ex, ey, ez] = sky.earth
    sunGroup.current.position.set(sx * SUN_DISTANCE, sy * SUN_DISTANCE, sz * SUN_DISTANCE)
    light.current.position.set(sx * 10, sy * 10, sz * 10)
    earthGroup.current.position.set(ex * EARTH_DISTANCE, ey * EARTH_DISTANCE, ez * EARTH_DISTANCE)
    earthMesh.current.rotation.y += dt * 0.12
  })

  return (
    <>
      <ambientLight intensity={0.26} color="#9fb4d6" />
      <directionalLight ref={light} intensity={3.4} color="#fff3dc" castShadow shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-1.5} shadow-camera-right={1.5} shadow-camera-top={1.5} shadow-camera-bottom={-1.5}
        shadow-camera-near={5} shadow-camera-far={15} shadow-bias={-0.0006} shadow-normalBias={0.02} />

      <group ref={sunGroup}>
        <mesh>
          <sphereGeometry args={[0.3, 48, 48]} />
          <meshBasicMaterial color="#ffe9b3" toneMapped={false} />
        </mesh>
        <sprite scale={[1.7, 1.7, 1]}><spriteMaterial map={corona} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.95} /></sprite>
        <sprite scale={[3.9, 3.9, 1]}><spriteMaterial map={corona} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.45} /></sprite>
        <TextSprite text="SUN" color="#f59e0b" border={false} position={[0, -0.5, 0]} height={0.034} />
      </group>

      <group ref={earthGroup}>
        <mesh ref={earthMesh}>
          <sphereGeometry args={[0.2, 48, 48]} />
          <meshStandardMaterial map={earthTex} emissive="#0b2a4a" emissiveIntensity={0.45} roughness={0.9} />
        </mesh>
        <sprite scale={[0.78, 0.78, 1]}><spriteMaterial map={halo} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.6} /></sprite>
        <TextSprite text="EARTH" color="#38bdf8" border={false} position={[0, -0.36, 0]} height={0.034} />
      </group>
    </>
  )
}
