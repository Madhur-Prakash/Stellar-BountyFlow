import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, type RefObject } from 'react'
import * as THREE from 'three'

import { motionAllowed } from '@/hooks/useReducedMotion'

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

/** Ripples a press can leave travelling across the field at once. */
const RIPPLES = 3

const vertex = /* glsl */ `
  uniform float uTime;
  uniform float uPixelRatio;
  uniform vec2 uPointer;
  uniform float uPointerStrength;
  // Each ripple is (x, z, start time); a negative start means the slot is free.
  uniform vec3 uRipples[${RIPPLES}];
  varying float vDepth;
  varying float vLift;
  void main() {
    vec3 p = position;
    float h = sin(p.x * 1.1 + uTime * 0.6) * 0.15 + sin(p.z * 1.7 + uTime * 0.45) * 0.09;

    // The field swells towards the pointer, so it feels touchable before anything is pressed.
    float toPointer = distance(p.xz, uPointer);
    float swell = exp(-toPointer * toPointer * 1.1) * uPointerStrength;
    h += swell * 0.26;

    // A press sends a ring outwards, fading as it goes.
    float crest = 0.0;
    for (int i = 0; i < ${RIPPLES}; i++) {
      float start = uRipples[i].z;
      if (start < 0.0) continue;
      float age = uTime - start;
      float edge = (distance(p.xz, uRipples[i].xy) - age * 1.7) * 2.1;
      crest += exp(-edge * edge) * max(0.0, 1.0 - age / 2.4);
    }
    h += crest * 0.3;

    vec4 mv = modelViewMatrix * vec4(vec3(p.x, h, p.z), 1.0);
    vDepth = clamp((-mv.z - 1.0) / 4.5, 0.0, 1.0);
    vLift = clamp(swell + crest, 0.0, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = 4.2 * (1.0 + vLift * 0.9) * uPixelRatio / -mv.z * 2.0;
  }
`
const fragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vDepth;
  varying float vLift;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    if (dot(c, c) > 0.25) discard;
    float alpha = (1.0 - vDepth) * uOpacity + vLift * 0.5;
    gl_FragColor = vec4(uColor, clamp(alpha, 0.0, 1.0));
  }
`

function Field({ theme, host }: { theme: ThreeTheme; host: RefObject<HTMLDivElement | null> }) {
  const material = useRef<THREE.ShaderMaterial>(null)
  const pixelRatio = useThree((s) => s.viewport.dpr)
  const invalidate = useThree((s) => s.invalidate)
  const camera = useThree((s) => s.camera)
  const positions = useMemo(() => gridPoints(), [])
  const pointer = useRef<{ x: number; y: number; inside: boolean; tap: boolean }>({
    x: 0,
    y: 0,
    inside: false,
    tap: false,
  })
  const next = useRef(0)
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uColor: { value: new THREE.Color('#3563e9') },
      uOpacity: { value: 0.45 },
      uPixelRatio: { value: 1 },
      uPointer: { value: new THREE.Vector2(0, -99) },
      uPointerStrength: { value: 0 },
      uRipples: { value: Array.from({ length: RIPPLES }, () => new THREE.Vector3(0, 0, -1)) },
    }),
    [],
  )

  /**
   * Pointer tracking on the window, hit-tested against the canvas.
   *
   * The field is a backdrop behind the heading and its two buttons, so the canvas keeps
   * `pointer-events: none` and the content in front of it stays clickable. Nothing calls `preventDefault`,
   * so a touch still scrolls the page.
   */
  useEffect(() => {
    const el = host.current
    if (!el) return
    const at = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect()
      const inside =
        e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom
      return {
        inside,
        x: ((e.clientX - rect.left) / rect.width) * 2 - 1,
        y: -((e.clientY - rect.top) / rect.height) * 2 + 1,
      }
    }
    const move = (e: PointerEvent) => {
      pointer.current = { ...at(e), tap: pointer.current.tap }
      if (pointer.current.inside) invalidate()
    }
    const down = (e: PointerEvent) => {
      const p = at(e)
      if (!p.inside) return
      pointer.current = { ...p, tap: true }
      invalidate()
    }
    const leave = () => {
      pointer.current = { ...pointer.current, inside: false }
    }
    window.addEventListener('pointermove', move, { passive: true })
    window.addEventListener('pointerdown', down, { passive: true })
    window.addEventListener('pointerleave', leave, { passive: true })
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerdown', down)
      window.removeEventListener('pointerleave', leave)
    }
  }, [host, invalidate])

  useEffect(() => {
    const m = material.current
    if (!m) return
    m.uniforms.uColor.value.set(theme.primary)
    m.uniforms.uOpacity.value = theme.dark ? 0.75 : 0.4
    m.uniforms.uPixelRatio.value = pixelRatio
    invalidate()
  }, [theme, pixelRatio, invalidate])

  useFrame((_, delta) => {
    const m = material.current
    if (!m) return
    m.uniforms.uTime.value += delta
    const t = m.uniforms.uTime.value as number
    const animate = motionAllowed()

    // Where the pointer meets the field's own plane (y = 0).
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
    const ray = new THREE.Raycaster()
    const hit = new THREE.Vector3()
    let on: THREE.Vector3 | null = null
    if (pointer.current.inside) {
      ray.setFromCamera(new THREE.Vector2(pointer.current.x, pointer.current.y), camera)
      on = ray.ray.intersectPlane(plane, hit)
    }

    const slots = m.uniforms.uRipples.value as THREE.Vector3[]
    const strength = m.uniforms.uPointerStrength as { value: number }
    const target = on ? 1 : 0
    strength.value += (target - strength.value) * (1 - Math.exp(-delta * (animate ? 5 : 60)))
    if (on) (m.uniforms.uPointer.value as THREE.Vector2).set(on.x, on.z)

    if (pointer.current.tap) {
      pointer.current.tap = false
      if (on) {
        slots[next.current % RIPPLES].set(on.x, on.z, t)
        next.current += 1
      }
    }

    // Retire ripples once they have faded, and keep drawing while any is alive.
    let alive = false
    for (let i = 0; i < RIPPLES; i++) {
      const start = slots[i].z
      if (start < 0) continue
      if (t - start > 2.4) slots[i].setZ(-1)
      else alive = true
    }
    if (alive || strength.value > 0.01) invalidate()
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
 * It swells towards the pointer and sends a ring outwards wherever it is pressed or tapped. Decorative only;
 * paused off screen and a still frame under reduced motion.
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
        <Field theme={theme} host={host} />
      </Canvas>
    </div>
  )
}
