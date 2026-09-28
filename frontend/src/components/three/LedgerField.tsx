import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'

import { useFrameloop } from './useFrameloop'
import { useThreeTheme, type ThreeTheme } from './useThreeTheme'

const COLUMNS = 120
const ROWS = 36
const SPACING = 0.09

/** A flat grid of points; the vertex shader lifts it into slow, overlapping waves. */
function gridPoints(): Float32Array {
  const out = new Float32Array(COLUMNS * ROWS * 3)
  let k = 0
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLUMNS; c++) {
      out[k++] = (c - COLUMNS / 2) * SPACING
      out[k++] = 0
      out[k++] = (r - ROWS / 2) * SPACING
    }
  }
  return out
}

const vertex = /* glsl */ `
  uniform float uTime;
  uniform float uPixelRatio;
  varying float vDepth;
  void main() {
    vec3 p = position;
    p.y = sin(p.x * 1.1 + uTime * 0.6) * 0.12 + sin(p.z * 1.7 + uTime * 0.45) * 0.08;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vDepth = clamp((-mv.z - 1.0) / 4.5, 0.0, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = 3.2 * uPixelRatio / -mv.z * 2.0;
  }
`
const fragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vDepth;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    if (dot(c, c) > 0.25) discard;
    gl_FragColor = vec4(uColor, (1.0 - vDepth) * uOpacity);
  }
`

function Field({ theme }: { theme: ThreeTheme }) {
  const material = useRef<THREE.ShaderMaterial>(null)
  const pixelRatio = useThree((s) => s.viewport.dpr)
  const invalidate = useThree((s) => s.invalidate)
  const positions = useMemo(() => gridPoints(), [])
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uColor: { value: new THREE.Color('#3563e9') },
      uOpacity: { value: 0.45 },
      uPixelRatio: { value: 1 },
    }),
    [],
  )

  useEffect(() => {
    const m = material.current
    if (!m) return
    m.uniforms.uColor.value.set(theme.primary)
    m.uniforms.uOpacity.value = theme.dark ? 0.55 : 0.45
    m.uniforms.uPixelRatio.value = pixelRatio
    invalidate()
  }, [theme, pixelRatio, invalidate])

  useFrame((_, delta) => {
    const m = material.current
    if (m) m.uniforms.uTime.value += delta
  })

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <shaderMaterial
        ref={material}
        vertexShader={vertex}
        fragmentShader={fragment}
        uniforms={uniforms}
        transparent
        depthWrite={false}
      />
    </points>
  )
}

/**
 * A field of dots rolling in slow waves, like rows of a ledger: the backdrop of the closing call to action.
 * Decorative only; paused off screen and a still frame under reduced motion.
 */
export default function LedgerField({ className }: { className?: string }) {
  const host = useRef<HTMLDivElement>(null)
  const frameloop = useFrameloop(host)
  const theme = useThreeTheme()
  return (
    <div ref={host} aria-hidden className={className}>
      <Canvas
        dpr={[1, 1.75]}
        frameloop={frameloop}
        camera={{ position: [0, 1.25, 2.6], fov: 50 }}
        onCreated={({ camera }) => camera.lookAt(0, 0, -0.4)}
        gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      >
        <Field theme={theme} />
      </Canvas>
    </div>
  )
}
