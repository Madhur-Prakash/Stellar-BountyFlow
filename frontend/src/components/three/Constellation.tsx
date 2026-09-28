import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, type CSSProperties } from 'react'
import * as THREE from 'three'

import { motionAllowed } from '@/hooks/useReducedMotion'

import { useFrameloop } from './useFrameloop'
import { useThreeTheme, type ThreeTheme } from './useThreeTheme'

/** Nodes in the network by default; small screens pass fewer. */
const NODE_COUNT = 170
/** Payments travelling through the network at any moment. */
const PULSES = 11
/** Points drawn per pulse: the head and a short fading tail. */
const TAIL = 5

/** Deterministic pseudo-random numbers (mulberry32), so the network looks the same on every visit. */
function random(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

type Network = {
  nodes: Float32Array
  phases: Float32Array
  neighbours: number[][]
  /** Line segment endpoints (two vertices per link) and each vertex's node phase. */
  lines: Float32Array
  linePhases: Float32Array
}

/**
 * A wide, shallow slab of nodes on a jittered grid (so they spread evenly), each linked to its nearest
 * neighbours.
 */
function buildNetwork(count: number): Network {
  const rand = random(11)
  const cols = Math.max(4, Math.round(Math.sqrt(count * 2.4)))
  const rows = Math.max(3, Math.ceil(count / cols))
  const width = 15
  const height = 6.4
  const nodes = new Float32Array(cols * rows * 3)
  const phases = new Float32Array(cols * rows)
  let n = 0
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      nodes[n * 3] = ((c + 0.5 + (rand() - 0.5) * 0.9) / cols - 0.5) * width
      nodes[n * 3 + 1] = ((r + 0.5 + (rand() - 0.5) * 0.9) / rows - 0.5) * height
      nodes[n * 3 + 2] = 0.6 - rand() * 3.6
      phases[n] = rand() * Math.PI * 2
      n++
    }
  }

  const neighbours: number[][] = Array.from({ length: n }, () => [])
  const pairs: [number, number][] = []
  const seen = new Set<number>()
  for (let i = 0; i < n; i++) {
    const near: [number, number][] = []
    for (let j = 0; j < n; j++) {
      if (j === i) continue
      const dx = nodes[i * 3] - nodes[j * 3]
      const dy = nodes[i * 3 + 1] - nodes[j * 3 + 1]
      const dz = nodes[i * 3 + 2] - nodes[j * 3 + 2]
      near.push([dx * dx + dy * dy + dz * dz, j])
    }
    near.sort((a, b) => a[0] - b[0])
    for (const [, j] of near.slice(0, 3)) {
      const key = Math.min(i, j) * n + Math.max(i, j)
      if (seen.has(key)) continue
      seen.add(key)
      pairs.push([i, j])
      neighbours[i].push(j)
      neighbours[j].push(i)
    }
  }

  const lines = new Float32Array(pairs.length * 6)
  const linePhases = new Float32Array(pairs.length * 2)
  pairs.forEach(([a, b], k) => {
    lines.set(nodes.subarray(a * 3, a * 3 + 3), k * 6)
    lines.set(nodes.subarray(b * 3, b * 3 + 3), k * 6 + 3)
    linePhases[k * 2] = phases[a]
    linePhases[k * 2 + 1] = phases[b]
  })
  return { nodes: nodes.subarray(0, n * 3), phases: phases.subarray(0, n), neighbours, lines, linePhases }
}

// Every node drifts on a slow loop of its own; the links follow the same motion, so the network breathes as one.
const drift = /* glsl */ `
  uniform float uTime;
  vec3 drift(vec3 p, float phase) {
    return p + vec3(cos(uTime * 0.23 + phase * 1.3) * 0.07, sin(uTime * 0.31 + phase) * 0.09, 0.0);
  }
  float depthFade(vec4 mv) {
    return mix(1.0, 0.3, clamp((-mv.z - 4.0) / 5.0, 0.0, 1.0));
  }
`

const nodeVertex = /* glsl */ `
  ${drift}
  attribute float aPhase;
  attribute float aGlow;
  uniform float uSize;
  uniform float uPixelRatio;
  varying float vAlpha;
  varying float vGlow;
  void main() {
    vec4 mv = modelViewMatrix * vec4(drift(position, aPhase), 1.0);
    gl_Position = projectionMatrix * mv;
    vAlpha = depthFade(mv) * (0.7 + 0.3 * sin(uTime * 1.1 + aPhase * 3.0));
    vGlow = aGlow;
    gl_PointSize = uSize * (1.0 + aGlow * 1.8) * uPixelRatio / -mv.z;
  }
`
const nodeFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform vec3 uGlowColor;
  uniform float uOpacity;
  varying float vAlpha;
  varying float vGlow;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float edge = smoothstep(0.5, 0.3, d);
    vec3 color = mix(uColor, uGlowColor, vGlow);
    gl_FragColor = vec4(color, edge * max(vAlpha * uOpacity, vGlow));
  }
`

const lineVertex = /* glsl */ `
  ${drift}
  attribute float aPhase;
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(drift(position, aPhase), 1.0);
    gl_Position = projectionMatrix * mv;
    vAlpha = depthFade(mv);
  }
`
const lineFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vAlpha;
  void main() {
    gl_FragColor = vec4(uColor, vAlpha * uOpacity);
  }
`

const pulseVertex = /* glsl */ `
  attribute float aFade;
  uniform float uSize;
  uniform float uPixelRatio;
  varying float vFade;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    vFade = aFade;
    gl_PointSize = uSize * (0.45 + 0.55 * aFade) * uPixelRatio / -mv.z;
  }
`
const pulseFragment = /* glsl */ `
  uniform vec3 uColor;
  varying float vFade;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    gl_FragColor = vec4(uColor, smoothstep(0.5, 0.05, d) * vFade);
  }
`

/** The same drift as the shaders, for placing pulses exactly on the moving links. */
function driftedNode(out: THREE.Vector3, nodes: Float32Array, phases: Float32Array, i: number, t: number) {
  const phase = phases[i]
  return out.set(
    nodes[i * 3] + Math.cos(t * 0.23 + phase * 1.3) * 0.07,
    nodes[i * 3 + 1] + Math.sin(t * 0.31 + phase) * 0.09,
    nodes[i * 3 + 2],
  )
}

type Pulse = { from: number; to: number; start: number; duration: number }

function Network({ theme, count }: { theme: ThreeTheme; count: number }) {
  const group = useRef<THREE.Group>(null)
  const nodeMaterial = useRef<THREE.ShaderMaterial>(null)
  const lineMaterial = useRef<THREE.ShaderMaterial>(null)
  const pulseMaterial = useRef<THREE.ShaderMaterial>(null)
  const nodePoints = useRef<THREE.Points>(null)
  const pulsePoints = useRef<THREE.Points>(null)
  const pulses = useRef<Pulse[] | null>(null)
  const pointer = useRef({ x: 0, y: 0 })
  const pixelRatio = useThree((s) => s.viewport.dpr)
  const invalidate = useThree((s) => s.invalidate)

  const network = useMemo(() => buildNetwork(count), [count])
  const glow = useMemo(() => new Float32Array(network.phases.length), [network])
  const pulsePositions = useMemo(() => new Float32Array(PULSES * TAIL * 3), [])
  const pulseFade = useMemo(() => new Float32Array(PULSES * TAIL), [])
  const uniforms = useMemo(
    () => ({
      node: {
        uTime: { value: 0 },
        uColor: { value: new THREE.Color('#69655c') },
        uGlowColor: { value: new THREE.Color('#3563e9') },
        uOpacity: { value: 0.6 },
        uSize: { value: 26 },
        uPixelRatio: { value: 1 },
      },
      line: {
        uTime: { value: 0 },
        uColor: { value: new THREE.Color('#69655c') },
        uOpacity: { value: 0.16 },
      },
      pulse: {
        uColor: { value: new THREE.Color('#3563e9') },
        uSize: { value: 64 },
        uPixelRatio: { value: 1 },
      },
    }),
    [],
  )

  // Theme colours and the pixel ratio reach the shaders here; redraw once for the still (demand) frame loop.
  useEffect(() => {
    const node = nodeMaterial.current
    const line = lineMaterial.current
    const pulse = pulseMaterial.current
    if (!node || !line || !pulse) return
    node.uniforms.uColor.value.set(theme.dots)
    node.uniforms.uGlowColor.value.set(theme.primary)
    node.uniforms.uOpacity.value = theme.dark ? 0.62 : 0.55
    node.uniforms.uPixelRatio.value = pixelRatio
    line.uniforms.uColor.value.set(theme.dots)
    line.uniforms.uOpacity.value = theme.dark ? 0.2 : 0.17
    pulse.uniforms.uColor.value.set(theme.primary)
    pulse.uniforms.uPixelRatio.value = pixelRatio
    invalidate()
  }, [theme, pixelRatio, invalidate])

  // The network leans a little towards the pointer, which is what makes its depth readable.
  useEffect(() => {
    if (!motionAllowed()) return
    const move = (e: PointerEvent) => {
      pointer.current.x = (e.clientX / window.innerWidth) * 2 - 1
      pointer.current.y = (e.clientY / window.innerHeight) * 2 - 1
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => window.removeEventListener('pointermove', move)
  }, [])

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime
    const node = nodeMaterial.current
    const line = lineMaterial.current
    if (node) node.uniforms.uTime.value = t
    if (line) line.uniforms.uTime.value = t

    const g = group.current
    if (g) {
      const ease = 1 - Math.exp(-delta * 2)
      const targetY = pointer.current.x * 0.16 + Math.sin(t * 0.06) * 0.08
      const targetX = pointer.current.y * 0.1
      g.rotation.y += (targetY - g.rotation.y) * ease
      g.rotation.x += (targetX - g.rotation.x) * ease
    }

    const { nodes, phases, neighbours } = network
    const nodeCount = phases.length
    const seedPulse = (i: number, start: number): Pulse => {
      const from = Math.floor(Math.random() * nodeCount)
      const options = neighbours[from]
      return {
        from,
        to: options[Math.floor(Math.random() * options.length)] ?? from,
        start,
        duration: 1 + (i % 3) * 0.35,
      }
    }
    pulses.current ??= Array.from({ length: PULSES }, (_, i) => seedPulse(i, t - (i / PULSES) * 1.2))
    const list = pulses.current

    const glowAttr = nodePoints.current?.geometry.getAttribute('aGlow') as THREE.BufferAttribute | undefined
    const glowArray = glowAttr?.array as Float32Array | undefined
    if (glowArray) {
      const decay = Math.exp(-delta * 1.8)
      for (let i = 0; i < glowArray.length; i++) glowArray[i] *= decay
    }

    const posAttr = pulsePoints.current?.geometry.getAttribute('position') as
      THREE.BufferAttribute | undefined
    const fadeAttr = pulsePoints.current?.geometry.getAttribute('aFade') as THREE.BufferAttribute | undefined
    const positions = posAttr?.array as Float32Array | undefined
    const fades = fadeAttr?.array as Float32Array | undefined
    const a = new THREE.Vector3()
    const b = new THREE.Vector3()
    list.forEach((pulse, i) => {
      let p = (t - pulse.start) / pulse.duration
      if (p >= 1) {
        // Arrived: the node lights up, and the payment carries on to one of its other neighbours.
        if (glowArray) glowArray[pulse.to] = 1
        const options = neighbours[pulse.to].filter((j) => j !== pulse.from)
        const next = options.length > 0 ? options[Math.floor(Math.random() * options.length)] : pulse.from
        list[i] = Math.random() < 0.12 ? seedPulse(i, t) : { ...pulse, from: pulse.to, to: next, start: t }
        p = 0
      }
      const current = list[i]
      if (!positions || !fades) return
      driftedNode(a, nodes, phases, current.from, t)
      driftedNode(b, nodes, phases, current.to, t)
      for (let k = 0; k < TAIL; k++) {
        const along = Math.max(0, p - k * 0.045)
        const idx = (i * TAIL + k) * 3
        positions[idx] = a.x + (b.x - a.x) * along
        positions[idx + 1] = a.y + (b.y - a.y) * along
        positions[idx + 2] = a.z + (b.z - a.z) * along
        fades[i * TAIL + k] = (1 - k / TAIL) * Math.min(1, p * 6, (1 - p) * 8 + 0.35)
      }
    })
    if (glowAttr) glowAttr.needsUpdate = true
    if (posAttr) posAttr.needsUpdate = true
    if (fadeAttr) fadeAttr.needsUpdate = true
  })

  return (
    <group ref={group}>
      <lineSegments>
        <bufferGeometry key={count}>
          <bufferAttribute attach="attributes-position" args={[network.lines, 3]} />
          <bufferAttribute attach="attributes-aPhase" args={[network.linePhases, 1]} />
        </bufferGeometry>
        <shaderMaterial
          ref={lineMaterial}
          vertexShader={lineVertex}
          fragmentShader={lineFragment}
          uniforms={uniforms.line}
          transparent
          depthWrite={false}
        />
      </lineSegments>
      <points ref={nodePoints}>
        <bufferGeometry key={count}>
          <bufferAttribute attach="attributes-position" args={[network.nodes, 3]} />
          <bufferAttribute attach="attributes-aPhase" args={[network.phases, 1]} />
          <bufferAttribute attach="attributes-aGlow" args={[glow, 1]} />
        </bufferGeometry>
        <shaderMaterial
          ref={nodeMaterial}
          vertexShader={nodeVertex}
          fragmentShader={nodeFragment}
          uniforms={uniforms.node}
          transparent
          depthWrite={false}
        />
      </points>
      <points ref={pulsePoints} frustumCulled={false}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[pulsePositions, 3]} />
          <bufferAttribute attach="attributes-aFade" args={[pulseFade, 1]} />
        </bufferGeometry>
        <shaderMaterial
          ref={pulseMaterial}
          vertexShader={pulseVertex}
          fragmentShader={pulseFragment}
          uniforms={uniforms.pulse}
          transparent
          depthWrite={false}
        />
      </points>
    </group>
  )
}

/**
 * A field of linked nodes behind the landing headline, with payments hopping from node to node and lighting
 * each one they reach: the Stellar network, quietly at work. It leans towards the pointer. Decorative only
 * (hidden from assistive technology); it stops drawing while off screen and is a still frame under reduced
 * motion.
 */
export default function Constellation({
  className,
  style,
  density = NODE_COUNT,
}: {
  className?: string
  style?: CSSProperties
  /** How many nodes make up the network. */
  density?: number
}) {
  const host = useRef<HTMLDivElement>(null)
  const frameloop = useFrameloop(host)
  const theme = useThreeTheme()
  return (
    <div ref={host} aria-hidden className={className} style={style}>
      <Canvas
        dpr={[1, 1.75]}
        frameloop={frameloop}
        camera={{ position: [0, 0, 6], fov: 50 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      >
        <Network theme={theme} count={density} />
      </Canvas>
    </div>
  )
}
