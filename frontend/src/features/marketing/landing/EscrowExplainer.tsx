import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin'
import { useRef, useState } from 'react'

import { PageContainer } from '@/components/layout/PageContainer'
import { Reveal } from '@/components/motion/Reveal'
import { motionAllowed } from '@/hooks/useReducedMotion'
import { useScrollEngineReady } from '@/hooks/useSmoothScroll'
import { gsap, ScrollTrigger, useGSAP } from '@/lib/gsap'

import { SectionHeading } from './SectionHeading'

gsap.registerPlugin(DrawSVGPlugin)

type StateId = 'created' | 'awaiting' | 'funded' | 'paid' | 'completed' | 'disputed' | 'cancel' | 'refunded'

type NodeDef = {
  id: StateId
  x: number
  y: number
  label: string
  sub: string
  tone: 'main' | 'ok' | 'warn' | 'alt'
  /** What this state means, shown when the state is hovered or focused. */
  detail: string
}

const W = 150
const H = 52

const NODES: NodeDef[] = [
  {
    id: 'created',
    x: 20,
    y: 40,
    label: 'Created',
    sub: 'bounty published',
    tone: 'main',
    detail:
      'The bounty is public and BountyFlow has prepared its escrow entry on the contract. No money has moved.',
  },
  {
    id: 'awaiting',
    x: 195,
    y: 40,
    label: 'Awaiting funding',
    sub: 'deposit in progress',
    tone: 'main',
    detail:
      'The requester is depositing reward × positions. A partial deposit shows as partly funded, never as funded.',
  },
  {
    id: 'funded',
    x: 370,
    y: 40,
    label: 'Funded',
    sub: 'reward × positions',
    tone: 'ok',
    detail: 'The full amount is confirmed in the contract. Only now does the bounty show “Funded in escrow”.',
  },
  {
    id: 'paid',
    x: 545,
    y: 40,
    label: 'Payout',
    sub: 'on approval',
    tone: 'main',
    detail:
      'An approved submission releases one position’s reward from the contract to the contributor’s verified wallet.',
  },
  {
    id: 'completed',
    x: 720,
    y: 40,
    label: 'Completed',
    sub: 'all positions paid',
    tone: 'ok',
    detail: 'Every position has been paid. The contract holds nothing more for this bounty.',
  },
  {
    id: 'disputed',
    x: 370,
    y: 190,
    label: 'Disputed',
    sub: 'arbiter decides',
    tone: 'warn',
    detail:
      'The escrow is frozen. The published arbiter can only pay the contributor or release the funds for a refund.',
  },
  {
    id: 'cancel',
    x: 545,
    y: 190,
    label: 'Cancel requested',
    sub: 'requester asks',
    tone: 'alt',
    detail:
      'The requester asked to cancel. A locked-in contributor must consent, or the deadline must pass, before a refund.',
  },
  {
    id: 'refunded',
    x: 720,
    y: 190,
    label: 'Refunded',
    sub: 'back to requester',
    tone: 'alt',
    detail: 'The funds went back to the requester’s wallet in a public refund transaction.',
  },
]

type EdgeDef = { d: string; from: StateId; to: StateId; dashed?: boolean }

const EDGES: EdgeDef[] = [
  { d: `M${20 + W} 66 H195`, from: 'created', to: 'awaiting' },
  { d: `M${195 + W} 66 H370`, from: 'awaiting', to: 'funded' },
  { d: `M${370 + W} 66 H545`, from: 'funded', to: 'paid' },
  { d: `M${545 + W} 66 H720`, from: 'paid', to: 'completed' },
  { d: `M445 92 V190`, from: 'funded', to: 'disputed', dashed: true },
  { d: `M480 92 C 500 140, 590 140, 620 190`, from: 'funded', to: 'cancel', dashed: true },
  { d: `M${545 + W} 216 H720`, from: 'cancel', to: 'refunded', dashed: true },
  { d: `M${370 + W} 205 C 540 150, 560 120, 590 92`, from: 'disputed', to: 'paid', dashed: true },
  { d: `M${370 + W} 228 C 560 280, 700 280, 760 242`, from: 'disputed', to: 'refunded', dashed: true },
]

/** Horizontal distance between neighbouring states on the normal path. */
const STRIDE = 175

const TONE: Record<NodeDef['tone'], { stroke: string; fill: string }> = {
  main: { stroke: 'var(--vault-line)', fill: 'var(--vault-node)' },
  ok: { stroke: 'var(--vault-green)', fill: 'var(--vault-node-ok)' },
  warn: { stroke: 'var(--vault-warn)', fill: 'var(--vault-node-warn)' },
  alt: { stroke: 'var(--vault-line)', fill: 'var(--vault-node-alt)' },
}

const STEPS = [
  [
    'Create',
    'The requester publishes the bounty. BountyFlow prepares an escrow entry on the Soroban contract.',
  ],
  [
    'Fund',
    'The requester signs a transfer of reward × positions into escrow. Only after the network confirms it does the bounty show as funded.',
  ],
  [
    'Deliver',
    'Accepted contributors do the work and submit it for review. The requester can lock an assignment on-chain so the reward cannot be refunded away.',
  ],
  [
    'Pay out',
    'Each approved submission releases one position’s reward from the contract to the contributor’s verified wallet.',
  ],
  [
    'Exceptions',
    'A cancelled bounty is refunded to the requester once any locked-in contributor consents or the deadline passes. A frozen dispute is routed by the published arbiter, who can only pay the contributor or release the funds for refund.',
  ],
] as const

const GUARANTEES = [
  [
    'You sign every transfer',
    'Funding, payouts, and refunds are transactions you review and sign in Freighter. BountyFlow never holds secret keys or recovery phrases.',
  ],
  [
    'Wallets are proven, not typed in',
    'A wallet is linked by signing a one-time challenge. Only signed proofs count as verified.',
  ],
  [
    'Everything is checkable',
    'Each funding and payout links to a public Stellar explorer, so you can confirm it without trusting us.',
  ],
  [
    'The network is always named',
    'Every transaction you review shows whether it runs on Testnet or Mainnet before you sign it.',
  ],
  [
    'Claims are labelled honestly',
    'Bios and skills are what people say about themselves. Only confirmed transactions count toward rewards and totals.',
  ],
] as const

type Emphasis = 'normal' | 'active' | 'dim'

/** One edge: the visible path (solid or dashed, with an arrowhead) revealed through a mask that DrawSVG draws. */
function Edge({ id, edge, emphasis }: { id: string; edge: EdgeDef; emphasis: Emphasis }) {
  const color = edge.dashed ? 'var(--vault-muted)' : 'var(--vault-accent)'
  return (
    <g>
      <mask id={id} maskUnits="userSpaceOnUse" x="-20" y="-20" width="930" height="330">
        <path data-draw d={edge.d} fill="none" stroke="white" strokeWidth="16" strokeLinecap="round" />
      </mask>
      <path
        d={edge.d}
        fill="none"
        strokeWidth={emphasis === 'active' ? 2.6 : 1.6}
        strokeDasharray={edge.dashed ? '5 5' : undefined}
        stroke={emphasis === 'active' ? 'var(--vault-accent)' : color}
        markerEnd={emphasis === 'active' || !edge.dashed ? 'url(#arrow-accent)' : 'url(#arrow-muted)'}
        mask={`url(#${id})`}
        className="transition-[opacity,stroke-width] duration-300"
        style={{ opacity: emphasis === 'dim' ? 0.18 : 1 }}
      />
    </g>
  )
}

function StateNode({
  node,
  emphasis,
  onHover,
}: {
  node: NodeDef
  emphasis: Emphasis
  onHover: (id: StateId | null) => void
}) {
  const tone = TONE[node.tone]
  return (
    // Outer group: faded in by the scroll timeline. Inner group: the hover and focus emphasis.
    <g data-node={node.id}>
      <g
        tabIndex={0}
        role="img"
        aria-label={`${node.label}: ${node.detail}`}
        onPointerEnter={() => onHover(node.id)}
        onPointerLeave={() => onHover(null)}
        onFocus={() => onHover(node.id)}
        onBlur={() => onHover(null)}
        className="cursor-default transition-[opacity,transform] duration-300 ease-out outline-none"
        style={{
          opacity: emphasis === 'dim' ? 0.3 : 1,
          transform: emphasis === 'active' ? 'scale(1.05)' : undefined,
          transformBox: 'fill-box',
          transformOrigin: 'center',
        }}
      >
        <rect
          x={node.x}
          y={node.y}
          width={W}
          height={H}
          rx="8"
          strokeWidth={emphasis === 'active' ? 2 : 1.25}
          stroke={emphasis === 'active' ? 'var(--vault-accent)' : tone.stroke}
          fill={tone.fill}
          style={{
            filter:
              emphasis === 'active'
                ? 'drop-shadow(0 8px 18px color-mix(in oklab, var(--vault-accent) 30%, transparent))'
                : undefined,
          }}
        />
        <text
          x={node.x + 14}
          y={node.y + 22}
          fill="var(--vault-foreground)"
          className="text-[13px] font-medium"
        >
          {node.label}
        </text>
        <text x={node.x + 14} y={node.y + 39} fill="var(--vault-muted)" className="text-[11px]">
          {node.sub}
        </text>
      </g>
    </g>
  )
}

function Lifecycle({ hovered, onHover }: { hovered: StateId | null; onHover: (id: StateId | null) => void }) {
  const connected = (e: EdgeDef) => hovered !== null && (e.from === hovered || e.to === hovered)
  const neighbours = new Set<StateId>(
    hovered ? [hovered, ...EDGES.filter(connected).flatMap((e) => [e.from, e.to])] : [],
  )
  const nodeEmphasis = (id: StateId): Emphasis =>
    hovered === null ? 'normal' : id === hovered ? 'active' : neighbours.has(id) ? 'normal' : 'dim'
  const edgeEmphasis = (e: EdgeDef): Emphasis =>
    hovered === null ? 'normal' : connected(e) ? 'active' : 'dim'
  const detail = NODES.find((n) => n.id === hovered)

  return (
    <figure
      data-lifecycle
      className="mt-12 hidden rounded-2xl border border-vault-line bg-vault-panel p-6 md:block lg:p-8"
    >
      <svg
        viewBox="0 24 890 266"
        overflow="visible"
        className="h-auto max-h-[calc(100svh-24rem)] w-full"
        role="group"
        aria-labelledby="escrow-diagram-title escrow-diagram-desc"
      >
        <title id="escrow-diagram-title">Escrow lifecycle</title>
        <desc id="escrow-diagram-desc">
          Created, awaiting funding, funded, payout, completed. From funded, a bounty can be disputed, where
          the arbiter releases funds to the contributor or refunds the requester, or cancelled by mutual
          consent, which refunds the requester.
        </desc>
        <defs>
          {(['accent', 'muted'] as const).map((tone) => (
            <marker
              key={tone}
              id={`arrow-${tone}`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path
                d="M0 0 L10 5 L0 10 z"
                fill={tone === 'accent' ? 'var(--vault-accent)' : 'var(--vault-muted)'}
              />
            </marker>
          ))}
        </defs>
        {/* The state the bounty is in as you scroll: a ring behind the state, moved along the normal path. It
            steps aside while you point at a state. */}
        <g
          aria-hidden
          className="pointer-events-none transition-opacity duration-300"
          style={{ opacity: hovered ? 0 : 1 }}
        >
          <rect
            data-current
            x={NODES[0].x - 6}
            y={NODES[0].y - 6}
            width={W + 12}
            height={H + 12}
            rx="12"
            fill="var(--vault-accent)"
            fillOpacity="0.14"
            stroke="var(--vault-accent)"
            strokeOpacity="0.45"
            strokeWidth="1"
            style={{ opacity: 0 }}
          />
        </g>
        <g data-main>
          {EDGES.filter((e) => !e.dashed).map((e, i) => (
            <Edge key={e.d} id={`escrow-main-${i}`} edge={e} emphasis={edgeEmphasis(e)} />
          ))}
        </g>
        <g data-exception>
          {EDGES.filter((e) => e.dashed).map((e, i) => (
            <Edge key={e.d} id={`escrow-exc-${i}`} edge={e} emphasis={edgeEmphasis(e)} />
          ))}
        </g>
        {NODES.map((n) => (
          <StateNode key={n.id} node={n} emphasis={nodeEmphasis(n.id)} onHover={onHover} />
        ))}
        <text data-exception-label x="530" y="140" fill="var(--vault-muted)" className="text-[10.5px]">
          release
        </text>
        <text data-exception-label x="600" y="285" fill="var(--vault-muted)" className="text-[10.5px]">
          refund
        </text>
      </svg>
      <figcaption className="mt-5 min-h-10 text-sm text-vault-muted" aria-live="polite">
        {detail ? (
          <>
            <span className="font-medium text-vault-foreground">{detail.label}.</span> {detail.detail}
          </>
        ) : (
          'Point at a state to see what it means on-chain. Solid: the normal path. Dashed: exception paths. The states mirror the contract’s escrow state machine.'
        )}
      </figcaption>
    </figure>
  )
}

export function EscrowExplainer() {
  const stage = useRef<HTMLDivElement>(null)
  const [hovered, setHovered] = useState<StateId | null>(null)
  const engine = useScrollEngineReady()

  // Pinned while you scroll: the states light up left to right while a ring follows the bounty along the normal
  // path, then the exception paths draw in. The section only moves on once the whole diagram is complete.
  useGSAP(
    () => {
      const el = stage.current
      // Wait for the page's scroll engine: the pin must be created against the engine it will live with.
      if (!el || engine === null) return
      const mm = gsap.matchMedia()
      mm.add('(min-width: 768px)', () => {
        if (!motionAllowed()) return
        const q = gsap.utils.selector(el)
        const nodes = q('[data-node]')
        const mainMasks = q('[data-main] [data-draw]')
        const exceptionMasks = q('[data-exception] [data-draw]')
        const labels = q('[data-exception-label]')
        const current = q('[data-current]')

        gsap.set([...mainMasks, ...exceptionMasks], { drawSVG: '0%' })
        gsap.set(nodes, { autoAlpha: 0.12 })
        gsap.set(labels, { autoAlpha: 0 })
        gsap.set(current, { autoAlpha: 0, x: 0 })

        // The ring moves from state i to the next while the arrow between them draws, and the next state lights
        // up as the ring arrives.
        const tl = gsap.timeline({ defaults: { ease: 'none' }, paused: true })
        tl.to([nodes[0], ...current], { autoAlpha: 1, duration: 0.3 }, 0)
        for (let i = 0; i < 4; i++) {
          tl.to(mainMasks[i], { drawSVG: '100%', duration: 0.6 }, i + 0.35)
            .to(current, { x: (i + 1) * STRIDE, duration: 0.6, ease: 'power2.inOut' }, i + 0.35)
            .to(nodes[i + 1], { autoAlpha: 1, duration: 0.3 }, i + 0.7)
        }
        tl.to(exceptionMasks, { drawSVG: '100%', duration: 1, stagger: 0.15 }, 4.4)
          .to(nodes.slice(5), { autoAlpha: 1, duration: 0.4, stagger: 0.15 }, 4.8)
          .to(labels, { autoAlpha: 1, duration: 0.4 }, 5.2)
          // A short hold with everything drawn before the pin releases.
          .to({}, { duration: 0.8 })

        // A standalone trigger (not the timeline's own): killing it with revert unwraps the pin spacer cleanly.
        const st = ScrollTrigger.create({
          animation: tl,
          trigger: el,
          start: 'top top+=72',
          end: () => `+=${Math.round(window.innerHeight * 1.8)}`,
          scrub: 0.8,
          pin: true,
          pinSpacing: true,
          anticipatePin: 1,
          invalidateOnRefresh: true,
        })
        return () => st.kill(true)
      })
      return () => mm.revert()
    },
    { scope: stage, dependencies: [engine], revertOnUpdate: true },
  )

  return (
    <section
      id="escrow"
      aria-labelledby="escrow-title"
      className="relative isolate overflow-hidden border-y border-vault-line bg-vault py-24 text-vault-foreground sm:py-28"
    >
      {/* Ledger grid, drifting slower than the page (ScrollSmoother data-speed on the story pages). */}
      <div
        aria-hidden
        data-speed="0.82"
        className="pointer-events-none absolute inset-x-0 -inset-y-40 -z-10 bg-[linear-gradient(var(--vault-line)_1px,transparent_1px),linear-gradient(90deg,var(--vault-line)_1px,transparent_1px)] mask-[radial-gradient(ellipse_70%_60%_at_50%_40%,black,transparent)] bg-size-[64px_64px] opacity-50"
      />
      <PageContainer>
        <div ref={stage}>
          <SectionHeading
            id="escrow-title"
            tone="vault"
            title="What happens to the money"
            description="Rewards sit in a Soroban smart contract on Stellar, not in a BountyFlow bank account. The contract only moves funds along the paths below."
          />
          <Lifecycle hovered={hovered} onHover={setHovered} />
        </div>

        <div className="mt-16 grid gap-12 lg:grid-cols-2 lg:gap-20">
          <div>
            <h3 id="escrow-path" className="text-lg font-semibold">
              The path of a reward
            </h3>
            <Reveal
              as="ol"
              aria-labelledby="escrow-path"
              className="mt-4 divide-y divide-vault-line border-y border-vault-line"
            >
              {STEPS.map(([title, text], i) => (
                <li key={title} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 py-4">
                  <span className="amount text-lg text-vault-accent">{i + 1}</span>
                  <div>
                    <p className="font-medium">{title}</p>
                    <p className="mt-1 text-[0.9375rem] leading-relaxed text-vault-muted">{text}</p>
                  </div>
                </li>
              ))}
            </Reveal>
          </div>
          <div>
            <h3 id="escrow-guarantees" className="text-lg font-semibold">
              What you can rely on
            </h3>
            <Reveal
              as="dl"
              aria-labelledby="escrow-guarantees"
              className="mt-4 divide-y divide-vault-line border-y border-vault-line"
            >
              {GUARANTEES.map(([title, text]) => (
                <div key={title} className="py-4">
                  <dt className="font-medium">{title}</dt>
                  <dd className="mt-1 text-[0.9375rem] leading-relaxed text-vault-muted">{text}</dd>
                </div>
              ))}
            </Reveal>
          </div>
        </div>
      </PageContainer>
    </section>
  )
}
