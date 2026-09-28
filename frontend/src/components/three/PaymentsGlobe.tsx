import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'

import { useFrameloop } from './useFrameloop'
import { useThreeTheme, type ThreeTheme } from './useThreeTheme'

const RADIUS = 1
const DOT_COUNT = 2400

/** Points spread evenly over a sphere (Fibonacci lattice). */
function spherePoints(count: number, radius: number): Float32Array {
  const out = new Float32Array(count * 3)
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2
    const ring = Math.sqrt(1 - y * y)
    const theta = golden * i
    out[i * 3] = Math.cos(theta) * ring * radius
    out[i * 3 + 1] = y * radius
    out[i * 3 + 2] = Math.sin(theta) * ring * radius
  }
  return out
}

function fromLatLng(lat: number, lng: number, radius: number): THREE.Vector3 {
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((lng + 180) * Math.PI) / 180
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  )
}

// Decorative hubs spread around the world, and the arcs drawn between them. Not data.
const HUBS: [number, number][] = [
  [40.7, -74],
  [51.5, -0.1],
  [6.5, 3.4],
  [19.1, 72.9],
  [1.35, 103.8],
  [35.7, 139.7],
  [-33.9, 151.2],
  [-23.5, -46.6],
  [37.8, -122.4],
  [52.5, 13.4],
  [-1.3, 36.8],
  [25.2, 55.3],
]
const LINKS: [number, number][] = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
  [4, 5],
  [5, 6],
  [7, 0],
  [8, 5],
  [9, 3],
  [10, 1],
  [11, 4],
  [7, 2],
]

/** Dots on the sphere fade out as they turn away from the camera, so the globe reads as solid without a fill. */
const dotVertex = /* glsl */ `
  uniform float uSize;
  uniform float uPixelRatio;
  varying float vFacing;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vFacing = normalize(normalMatrix * normalize(position)).z;
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * uPixelRatio / -mv.z;
  }
`
const dotFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vFacing;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    if (dot(c, c) > 0.25) discard;
    float a = smoothstep(-0.15, 0.55, vFacing);
    gl_FragColor = vec4(uColor, a * uOpacity);
  }
`

function Globe({ theme }: { theme: ThreeTheme }) {
  const group = useRef<THREE.Group>(null)
  const dotMaterial = useRef<THREE.ShaderMaterial>(null)
  const pulses = useRef<(THREE.Mesh | null)[]>([])
  const pixelRatio = useThree((s) => s.viewport.dpr)
  const invalidate = useThree((s) => s.invalidate)

  const positions = useMemo(() => spherePoints(DOT_COUNT, RADIUS), [])
  const uniforms = useMemo(
    () => ({
      uColor: { value: new THREE.Color('#6b6b75') },
      uOpacity: { value: 0.5 },
      uSize: { value: 5 },
      uPixelRatio: { value: 1 },
    }),
    [],
  )
  const arcs = useMemo(
    () =>
      LINKS.map(([a, b]) => {
        const from = fromLatLng(...HUBS[a], RADIUS)
        const to = fromLatLng(...HUBS[b], RADIUS)
        const mid = from.clone().add(to).multiplyScalar(0.5)
        mid.normalize().multiplyScalar(RADIUS * (1 + from.distanceTo(to) * 0.32))
        return new THREE.QuadraticBezierCurve3(from, mid, to)
      }),
    [],
  )
  const hubs = useMemo(() => HUBS.map(([lat, lng]) => fromLatLng(lat, lng, RADIUS * 1.002)), [])

  // Theme colours and the pixel ratio reach the dot shader here; redraw once for the still (demand) frame loop.
  useEffect(() => {
    const material = dotMaterial.current
    if (!material) return
    material.uniforms.uColor.value.set(theme.dots)
    material.uniforms.uOpacity.value = theme.dark ? 0.55 : 0.5
    material.uniforms.uPixelRatio.value = pixelRatio
    invalidate()
  }, [theme, pixelRatio, invalidate])

  useFrame((state, delta) => {
    if (group.current) group.current.rotation.y += delta * 0.05
    const t = state.clock.elapsedTime
    pulses.current.forEach((mesh, i) => {
      if (!mesh) return
      const p = (t * 0.22 + i / arcs.length) % 1
      mesh.position.copy(arcs[i].getPoint(p))
      const glow = Math.sin(p * Math.PI)
      mesh.scale.setScalar(0.5 + glow)
      ;(mesh.material as THREE.MeshBasicMaterial).opacity = glow * 0.9
    })
  })

  return (
    <group ref={group} rotation={[0.3, -1.1, 0.08]}>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        </bufferGeometry>
        <shaderMaterial
          ref={dotMaterial}
          vertexShader={dotVertex}
          fragmentShader={dotFragment}
          uniforms={uniforms}
          transparent
          depthWrite={false}
        />
      </points>
      {arcs.map((curve, i) => (
        <mesh key={i}>
          <tubeGeometry args={[curve, 64, 0.0022, 6, false]} />
          <meshBasicMaterial color={theme.primary} transparent opacity={0.35} depthWrite={false} />
        </mesh>
      ))}
      {hubs.map((position, i) => (
        <mesh key={i} position={position}>
          <sphereGeometry args={[0.012, 12, 12]} />
          <meshBasicMaterial color={theme.primary} />
        </mesh>
      ))}
      {arcs.map((_, i) => (
        <mesh
          key={i}
          ref={(m) => {
            pulses.current[i] = m
          }}
        >
          <sphereGeometry args={[0.014, 12, 12]} />
          <meshBasicMaterial color={theme.primary} transparent opacity={0} depthWrite={false} />
        </mesh>
      ))}
    </group>
  )
}

/**
 * A slowly turning dotted globe with arcs and travelling pulses: a quiet picture of payments moving across a
 * global network. Decorative only (hidden from assistive technology). It stops drawing while off screen and is
 * a still frame under reduced motion.
 */
export default function PaymentsGlobe({ className }: { className?: string }) {
  const host = useRef<HTMLDivElement>(null)
  const frameloop = useFrameloop(host)
  const theme = useThreeTheme()
  return (
    <div ref={host} aria-hidden className={className}>
      <Canvas
        dpr={[1, 1.75]}
        frameloop={frameloop}
        camera={{ position: [0, 0, 3.05], fov: 40 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      >
        <Globe theme={theme} />
      </Canvas>
    </div>
  )
}
