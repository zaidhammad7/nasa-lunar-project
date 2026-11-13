import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import TextSprite from './TextSprite.jsx'
import StarField from './StarField.jsx'
import { useEarthTextures } from './textures.js'
import { sky, updateSky, SUN_DISTANCE, SUN_RADIUS, EARTH_DISTANCE, EARTH_RADIUS } from './sky.js'

/** Advances the shared sky state from the mission clock once per frame (must be mounted before the bodies). */
export function SkyClock() {
  useFrame(() => updateSky())
  return null
}

function glowTexture(inner, mid) {
  const c = document.createElement('canvas'); c.width = c.height = 256
  const ctx = c.getContext('2d'), g = ctx.createRadialGradient(128, 128, 0, 128, 128, 128)
  g.addColorStop(0, inner); g.addColorStop(0.3, mid); g.addColorStop(1, 'rgba(255,140,0,0)')
  ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 256)
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace
  return t
}

/**
 * TRUE 1:1 scale (1 unit = 1737.4 km): Moon r = 1, Earth r = 3.668 at 221.2 units, Sun r = 400.8 at 86,105 units
 * (so the Sun subtends the real 0.53 deg). Directions come from the physics model; the shadow-casting directional light
 * sits on the same Sun vector.
 */
export default function CelestialBodies() {
  const sunGroup = useRef(), earthGroup = useRef(), earthMesh = useRef(), cloudMesh = useRef(), light = useRef()
  const earthTex = useEarthTextures()
  const corona = useMemo(() => glowTexture('rgba(255,244,200,1)', 'rgba(255,176,60,0.32)'), [])

  useFrame((_, dt) => {
    const [sx, sy, sz] = sky.sun, [ex, ey, ez] = sky.earth
    sunGroup.current.position.set(sx * SUN_DISTANCE, sy * SUN_DISTANCE, sz * SUN_DISTANCE)
    light.current.position.set(sx * 50, sy * 50, sz * 50)
    earthGroup.current.position.set(ex * EARTH_DISTANCE, ey * EARTH_DISTANCE, ez * EARTH_DISTANCE)
    earthMesh.current.rotation.y += dt * 0.08
    if (cloudMesh.current) cloudMesh.current.rotation.y += dt * 0.1
  })

  return (
    <>
      <StarField count={6000} radius={50000} />
      <ambientLight intensity={0.26} color="#9fb4d6" />
      <directionalLight ref={light} intensity={3.4} color="#fff3dc" castShadow shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-1.6} shadow-camera-right={1.6} shadow-camera-top={1.6} shadow-camera-bottom={-1.6}
        shadow-camera-near={40} shadow-camera-far={60} shadow-bias={-0.0004} shadow-normalBias={0.02} />

      <group ref={sunGroup}>
        <mesh>
          <sphereGeometry args={[SUN_RADIUS, 64, 64]} />
          <meshBasicMaterial color="#fff1c9" toneMapped={false} />
        </mesh>
        <sprite scale={[SUN_RADIUS * 3.4, SUN_RADIUS * 3.4, 1]}><spriteMaterial map={corona} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.9} /></sprite>
        <sprite scale={[SUN_RADIUS * 9, SUN_RADIUS * 9, 1]}><spriteMaterial map={corona} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.4} /></sprite>
        <sprite scale={[SUN_RADIUS * 22, SUN_RADIUS * 22, 1]}><spriteMaterial map={corona} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.14} /></sprite>
        <TextSprite text="SUN" color="#f59e0b" border={false} anchorTop position={[0, 0, -SUN_RADIUS * 2.4]} height={0.03} />
      </group>

      <group ref={earthGroup}>
        <mesh ref={earthMesh}>
          <sphereGeometry args={[EARTH_RADIUS, 96, 96]} />
          <meshStandardMaterial map={earthTex.map} emissiveMap={earthTex.map} emissive="#ffffff" emissiveIntensity={0.09} roughness={0.85} metalness={0} />
        </mesh>
        {earthTex.clouds && (
          <mesh ref={cloudMesh}>
            <sphereGeometry args={[EARTH_RADIUS * 1.008, 96, 96]} />
            <meshStandardMaterial map={earthTex.clouds} transparent depthWrite={false} roughness={1} />
          </mesh>
        )}
        {/* atmospheric rim: back-faces of a slightly larger additive shell show as a thin cyan glow around the limb */}
        <mesh>
          <sphereGeometry args={[EARTH_RADIUS * 1.07, 64, 64]} />
          <meshBasicMaterial color="#38bdf8" transparent opacity={0.2} side={THREE.BackSide} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
        <TextSprite text="EARTH" color="#38bdf8" border={false} anchorTop position={[0, 0, -EARTH_RADIUS * 1.35]} height={0.03} />
      </group>
    </>
  )
}
