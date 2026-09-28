import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, type CSSProperties, type RefObject } from 'react'
import * as THREE from 'three'

import { motionAllowed } from '@/hooks/useReducedMotion'

import { useFrameloop } from './useFrameloop'
import { useThreeTheme, type ThreeTheme } from './useThreeTheme'

const RADIUS = 1
/** Dots on the sphere by default; a larger canvas wants more so the lattice stays fine. */
const DOT_COUNT = 2400
/** The globe's resting tilt and its idle spin (radians per second). */
const REST_TILT = 0.3
const AUTO_SPIN = 0.05
/** Radians of turn per pixel dragged. */
const DRAG_SPEED = 0.0045
/** Payments that can be in flight from clicks at once, and how many hubs each one reaches. */
const BURSTS = 4
const BURST_ARCS = 3
/** Seconds for a clicked payment's arcs to draw, and for the whole burst to fade. */
const BURST_DRAW = 0.9
const BURST_LIFE = 2.4
const TUBE_SEGMENTS = 48
const TUBE_SIDES = 6

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

/** An arc between two points on the sphere, rising higher the further apart they are. */
function arcBetween(from: THREE.Vector3, to: THREE.Vector3): THREE.QuadraticBezierCurve3 {
  const mid = from.clone().add(to).multiplyScalar(0.5)
  mid.normalize().multiplyScalar(RADIUS * (1 + from.distanceTo(to) * 0.32))
  return new THREE.QuadraticBezierCurve3(from.clone(), mid, to.clone())
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

/** A payment sent from a clicked point: arcs to the nearest hubs, drawn out and then faded. */
type Burst = { start: number; curves: THREE.QuadraticBezierCurve3[]; hubs: number[]; arrived: boolean[] }

/** Where the pointer is and what it is doing, shared by the DOM handlers and the frame loop. */
type Pointer = {
  dragging: boolean
  id: number
  x: number
  y: number
  moved: number
  time: number
  velocity: number
  hover: boolean
}

function Globe({
  theme,
  density,
  dotSize,
  markerScale,
  host,
}: {
  theme: ThreeTheme
  density: number
  dotSize: number
  markerScale: number
  host: RefObject<HTMLDivElement | null>
}) {
  const tilt = useRef<THREE.Group>(null)
  const spin = useRef<THREE.Group>(null)
  const dotMaterial = useRef<THREE.ShaderMaterial>(null)
  const pulses = useRef<(THREE.Mesh | null)[]>([])
  const hubMeshes = useRef<(THREE.Mesh | null)[]>([])
  const hubFlash = useRef<number[]>(HUBS.map(() => -Infinity))
  const burstTubes = useRef<(THREE.Mesh | null)[]>([])
  const burstHeads = useRef<(THREE.Mesh | null)[]>([])
  const burstRings = useRef<(THREE.Mesh | null)[]>([])
  const bursts = useRef<(Burst | null)[]>(Array.from({ length: BURSTS }, () => null))
  const nextBurst = useRef(0)
  const pointer = useRef<Pointer>({
    dragging: false,
    id: -1,
    x: 0,
    y: 0,
    moved: 0,
    time: 0,
    velocity: AUTO_SPIN,
    hover: false,
  })
  const pixelRatio = useThree((s) => s.viewport.dpr)
  const invalidate = useThree((s) => s.invalidate)
  const camera = useThree((s) => s.camera)

  const positions = useMemo(() => spherePoints(density, RADIUS), [density])
  const uniforms = useMemo(
    () => ({
      uColor: { value: new THREE.Color('#6b6b75') },
      uOpacity: { value: 0.5 },
      uSize: { value: dotSize },
      uPixelRatio: { value: 1 },
    }),
    [dotSize],
  )
  const arcs = useMemo(
    () => LINKS.map(([a, b]) => arcBetween(fromLatLng(...HUBS[a], RADIUS), fromLatLng(...HUBS[b], RADIUS))),
    [],
  )
  const hubs = useMemo(() => HUBS.map(([lat, lng]) => fromLatLng(lat, lng, RADIUS * 1.002)), [])

  // Theme colours and the pixel ratio reach the dot shader here; redraw once for the still (demand) frame loop.
  useEffect(() => {
    const material = dotMaterial.current
    if (!material) return
    material.uniforms.uColor.value.set(theme.dots)
    material.uniforms.uPixelRatio.value = pixelRatio
    invalidate()
  }, [theme, pixelRatio, invalidate])

  // Drag to turn the globe (it keeps some spin when let go); click it to send a payment from that point.
  useEffect(() => {
    const el = host.current
    if (!el) return
    const animate = motionAllowed()
    const raycaster = new THREE.Raycaster()
    const sphere = new THREE.Sphere(new THREE.Vector3(), RADIUS)
    const state = pointer.current

    /** The point on the globe under the pointer, in the spinning globe's own coordinates. */
    const pick = (e: PointerEvent): THREE.Vector3 | null => {
      const rect = el.getBoundingClientRect()
      const ndc = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      )
      raycaster.setFromCamera(ndc, camera)
      const hit = raycaster.ray.intersectSphere(sphere, new THREE.Vector3())
      return hit && spin.current ? spin.current.worldToLocal(hit) : null
    }

    const send = (point: THREE.Vector3) => {
      const origin = point.normalize().multiplyScalar(RADIUS * 1.002)
      const nearest = hubs
        .map((h, i) => [h.distanceTo(origin), i] as const)
        .filter(([d]) => d > 0.12)
        .sort((a, b) => a[0] - b[0])
        .slice(0, BURST_ARCS)
        .map(([, i]) => i)
      const slot = nextBurst.current
      nextBurst.current = (slot + 1) % BURSTS
      const curves = nearest.map((i) => arcBetween(origin, hubs[i]))
      curves.forEach((curve, k) => {
        const tube = burstTubes.current[slot * BURST_ARCS + k]
        if (!tube) return
        tube.geometry.dispose()
        tube.geometry = new THREE.TubeGeometry(curve, TUBE_SEGMENTS, 0.005 * markerScale, TUBE_SIDES, false)
        tube.geometry.setDrawRange(0, 0)
        tube.visible = true
      })
      const ring = burstRings.current[slot]
      if (ring) {
        ring.position.copy(origin)
        ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), origin.clone().normalize())
        ring.visible = true
      }
      bursts.current[slot] = {
        start: performance.now() / 1000,
        curves,
        hubs: nearest,
        arrived: nearest.map(() => false),
      }
      invalidate()
      // Without motion there are no frames to fade the burst, so clear it with one more still frame.
      if (!animate) window.setTimeout(invalidate, BURST_LIFE * 1000 + 50)
    }

    const setCursor = () => {
      el.style.cursor = state.dragging ? 'grabbing' : state.hover ? 'grab' : ''
    }

    const down = (e: PointerEvent) => {
      if (e.button !== 0 || !pick(e)) return
      state.dragging = true
      state.id = e.pointerId
      state.x = e.clientX
      state.y = e.clientY
      state.moved = 0
      state.time = e.timeStamp
      state.velocity = 0
      el.setPointerCapture(e.pointerId)
      setCursor()
    }
    const move = (e: PointerEvent) => {
      if (state.dragging && e.pointerId === state.id) {
        const dx = e.clientX - state.x
        const dy = e.clientY - state.y
        const dt = Math.max(1, e.timeStamp - state.time) / 1000
        state.x = e.clientX
        state.y = e.clientY
        state.time = e.timeStamp
        state.moved += Math.abs(dx) + Math.abs(dy)
        if (spin.current) spin.current.rotation.y += dx * DRAG_SPEED
        if (tilt.current) {
          tilt.current.rotation.x = THREE.MathUtils.clamp(
            tilt.current.rotation.x + dy * DRAG_SPEED,
            -0.35,
            0.95,
          )
        }
        const instant = THREE.MathUtils.clamp((dx * DRAG_SPEED) / dt, -6, 6)
        state.velocity = state.velocity * 0.5 + instant * 0.5
        invalidate()
        return
      }
      const over = pick(e) !== null
      if (over !== state.hover) {
        state.hover = over
        setCursor()
        invalidate()
      }
    }
    const up = (e: PointerEvent) => {
      if (!state.dragging || e.pointerId !== state.id) return
      state.dragging = false
      if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId)
      // A press that barely moved is a click: send a payment from where it landed.
      if (e.type === 'pointerup' && state.moved < 6) {
        const point = pick(e)
        if (point) send(point)
        state.velocity = AUTO_SPIN
      }
      // Without motion the globe stops where it was let go.
      if (!animate) state.velocity = 0
      setCursor()
    }
    const leave = () => {
      if (state.dragging) return
      state.hover = false
      setCursor()
      invalidate()
    }

    el.addEventListener('pointerdown', down)
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
    el.addEventListener('pointercancel', up)
    el.addEventListener('pointerleave', leave)
    return () => {
      el.removeEventListener('pointerdown', down)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
      el.removeEventListener('pointercancel', up)
      el.removeEventListener('pointerleave', leave)
    }
  }, [host, camera, hubs, markerScale, invalidate])

  useFrame((state, delta) => {
    const input = pointer.current
    const animate = motionAllowed()

    // Let go, the globe keeps its spin and eases back to the idle turn and the resting tilt.
    if (!input.dragging && animate) {
      input.velocity += (AUTO_SPIN - input.velocity) * (1 - Math.exp(-delta * 1.1))
      if (spin.current) spin.current.rotation.y += input.velocity * delta
      if (tilt.current)
        tilt.current.rotation.x += (REST_TILT - tilt.current.rotation.x) * (1 - Math.exp(-delta * 0.7))
    }

    // The lattice brightens a little under the pointer.
    const material = dotMaterial.current
    if (material) {
      const base = theme.dark ? 0.55 : 0.5
      const target = base + (input.hover || input.dragging ? 0.2 : 0)
      const current = material.uniforms.uOpacity.value as number
      material.uniforms.uOpacity.value = animate
        ? current + (target - current) * (1 - Math.exp(-delta * 6))
        : target
    }

    const t = state.clock.elapsedTime
    pulses.current.forEach((mesh, i) => {
      if (!mesh) return
      const p = (t * 0.22 + i / arcs.length) % 1
      mesh.position.copy(arcs[i].getPoint(p))
      const glow = Math.sin(p * Math.PI)
      mesh.scale.setScalar(0.5 + glow)
      ;(mesh.material as THREE.MeshBasicMaterial).opacity = glow * 0.9
    })

    const now = performance.now() / 1000
    bursts.current.forEach((burst, slot) => {
      if (!burst) return
      const age = now - burst.start
      const ring = burstRings.current[slot]
      if (age > BURST_LIFE) {
        for (let k = 0; k < BURST_ARCS; k++) {
          const tube = burstTubes.current[slot * BURST_ARCS + k]
          const head = burstHeads.current[slot * BURST_ARCS + k]
          if (tube) tube.visible = false
          if (head) head.visible = false
        }
        if (ring) ring.visible = false
        bursts.current[slot] = null
        return
      }
      const drawn = animate ? Math.min(1, age / BURST_DRAW) : 1
      const eased = 1 - (1 - drawn) ** 3
      const fade = age < BURST_DRAW ? 1 : Math.max(0, 1 - (age - BURST_DRAW) / (BURST_LIFE - BURST_DRAW))
      burst.curves.forEach((curve, k) => {
        const tube = burstTubes.current[slot * BURST_ARCS + k]
        const head = burstHeads.current[slot * BURST_ARCS + k]
        if (tube) {
          tube.geometry.setDrawRange(0, Math.floor(eased * TUBE_SEGMENTS) * TUBE_SIDES * 6)
          ;(tube.material as THREE.MeshBasicMaterial).opacity = 0.85 * fade
        }
        if (head) {
          head.visible = drawn < 1
          head.position.copy(curve.getPoint(eased))
        }
        if (drawn >= 1 && !burst.arrived[k]) {
          burst.arrived[k] = true
          hubFlash.current[burst.hubs[k]] = now
        }
      })
      if (ring) {
        const spread = animate ? Math.min(1, age / 1.1) : 1
        ring.scale.setScalar(1 + spread * 5)
        ;(ring.material as THREE.MeshBasicMaterial).opacity = animate ? 0.7 * (1 - spread) : 0.4 * fade
      }
    })

    // A hub that a payment reaches swells for a moment.
    hubMeshes.current.forEach((mesh, i) => {
      if (!mesh) return
      const since = now - hubFlash.current[i]
      mesh.scale.setScalar(1 + (since >= 0 && since < 1.5 ? 2.4 * Math.exp(-since * 3) : 0))
    })
  })

  return (
    <group ref={tilt} rotation={[REST_TILT, 0, 0.08]}>
      <group ref={spin} rotation={[0, -1.1, 0]}>
        {/* Depth only: hides arcs and pulses on the far side, so the dotted sphere reads as solid. */}
        <mesh renderOrder={-1}>
          <sphereGeometry args={[RADIUS * 0.985, 64, 48]} />
          <meshBasicMaterial colorWrite={false} />
        </mesh>
        <points>
          <bufferGeometry key={density}>
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
            <tubeGeometry args={[curve, 64, 0.0022 * markerScale, 6, false]} />
            <meshBasicMaterial
              color={theme.primary}
              transparent
              opacity={markerScale < 1 ? 0.28 : 0.35}
              depthWrite={false}
            />
          </mesh>
        ))}
        {hubs.map((position, i) => (
          <mesh
            key={i}
            position={position}
            ref={(m) => {
              hubMeshes.current[i] = m
            }}
          >
            <sphereGeometry args={[0.012 * markerScale, 12, 12]} />
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
            <sphereGeometry args={[0.014 * markerScale, 12, 12]} />
            <meshBasicMaterial color={theme.primary} transparent opacity={0} depthWrite={false} />
          </mesh>
        ))}
        {Array.from({ length: BURSTS * BURST_ARCS }, (_, i) => (
          <mesh
            key={`burst-${i}`}
            visible={false}
            ref={(m) => {
              burstTubes.current[i] = m
            }}
          >
            <bufferGeometry />
            <meshBasicMaterial color={theme.primary} transparent opacity={0.85} depthWrite={false} />
          </mesh>
        ))}
        {Array.from({ length: BURSTS * BURST_ARCS }, (_, i) => (
          <mesh
            key={`head-${i}`}
            visible={false}
            ref={(m) => {
              burstHeads.current[i] = m
            }}
          >
            <sphereGeometry args={[0.02 * markerScale, 12, 12]} />
            <meshBasicMaterial color={theme.primary} />
          </mesh>
        ))}
        {Array.from({ length: BURSTS }, (_, i) => (
          <mesh
            key={`ring-${i}`}
            visible={false}
            ref={(m) => {
              burstRings.current[i] = m
            }}
          >
            <ringGeometry args={[0.012 * markerScale, 0.018 * markerScale, 48]} />
            <meshBasicMaterial
              color={theme.primary}
              transparent
              opacity={0}
              depthWrite={false}
              side={THREE.DoubleSide}
            />
          </mesh>
        ))}
      </group>
    </group>
  )
}

/**
 * A dotted globe with arcs and travelling pulses: a picture of payments moving across a global network, rising
 * behind the landing page's Stellar stack. Drag it to turn it, and click it to send a payment from that spot to
 * the nearest hubs. Decorative only (hidden from assistive technology); page scrolling still works over it on
 * touch screens. It stops drawing while off screen, and under reduced motion it only moves while dragged.
 */
export default function PaymentsGlobe({
  className,
  style,
  density = DOT_COUNT,
  dotSize = 5,
  markerScale = 1,
}: {
  className?: string
  style?: CSSProperties
  /** How many dots make up the sphere. */
  density?: number
  /** Dot size before perspective. */
  dotSize?: number
  /** Size of the hubs, pulses and arcs relative to the default; below 1 for a globe drawn very large. */
  markerScale?: number
}) {
  const host = useRef<HTMLDivElement>(null)
  const frameloop = useFrameloop(host)
  const theme = useThreeTheme()
  return (
    <div ref={host} aria-hidden className={className} style={{ touchAction: 'pan-y', ...style }}>
      <Canvas
        dpr={[1, 1.75]}
        frameloop={frameloop}
        camera={{ position: [0, 0, 3.05], fov: 40 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      >
        <Globe theme={theme} density={density} dotSize={dotSize} markerScale={markerScale} host={host} />
      </Canvas>
    </div>
  )
}
