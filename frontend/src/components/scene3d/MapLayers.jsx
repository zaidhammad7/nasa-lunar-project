import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import TextSprite from './TextSprite.jsx'
import { surfacePoint } from './MoonSphere.jsx'
import { buildHeatCanvas, CAP_LAT_MIN } from '../../lib/heatmap.js'
import { LANDMARKS } from '../../lib/landmarks.js'

const D2R = Math.PI / 180
const NO_HIT = () => null // overlays never intercept Moon clicks

/** Semi-transparent suitability field draped over the study cap (interpolated from the scored sites). */
export function HeatmapCap({ sites, opacity = 0.55 }) {
  const tex = useMemo(() => {
    const t = new THREE.CanvasTexture(buildHeatCanvas(sites))
    t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping; t.anisotropy = 4
    return t
  }, [sites])
  useEffect(() => () => tex.dispose(), [tex])
  const thetaStart = (90 - CAP_LAT_MIN) * D2R // polar angle from +Y (north) to the cap edge
  return (
    <mesh raycast={NO_HIT} renderOrder={2}>
      <sphereGeometry args={[1.0015, 256, 32, 0, Math.PI * 2, thetaStart, Math.PI - thetaStart]} />
      <meshBasicMaterial map={tex} transparent opacity={opacity} depthWrite={false} toneMapped={false} />
    </mesh>
  )
}

const POLE = new THREE.Vector3(0, -1, 0)
const LABEL_RANGE = 1.0 // scene units: labels only appear once the camera is this close to the pole (they overlap from afar)

/** Small labelled dots for the named south-polar craters. */
export function CraterLabels() {
  const grp = useRef()
  useFrame(({ camera }) => { if (grp.current) grp.current.visible = camera.position.distanceTo(POLE) < LABEL_RANGE })
  return <group ref={grp}>{LANDMARKS.map((l) => (
    <group key={l.name} position={surfacePoint(l.lat, l.lon, 0.004)}>
      <mesh raycast={NO_HIT}><sphereGeometry args={[0.0018, 10, 10]} /><meshBasicMaterial color="#e2e8f0" toneMapped={false} /></mesh>
      <TextSprite text={l.name} color="#e2e8f0" border={false} anchorTop position={[0, 0, 0]} height={0.016} />
    </group>
  ))}</group>
}
