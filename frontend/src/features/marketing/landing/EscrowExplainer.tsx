import { CheckCircle2 } from 'lucide-react'
import { useRef, useState } from 'react'

import { PageContainer } from '@/components/layout/PageContainer'
import { useScrollStory, useScrollStoryEnabled, type ScrollStoryTools } from '@/hooks/useScrollStory'

import { SECTION, SectionHeading } from './SectionHeading'

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
/** Horizontal distance between neighbouring states on the normal path. */
const STRIDE = 175

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

/**
 * One edge: solid for the normal path, dashed for exception paths, with an arrowhead. It is revealed through a
 * mask whose stroke the scroll story draws (DrawSVG), which works for dashed lines as well as solid ones.
 */
function Edge({ id, edge, emphasis }: { id: string; edge: EdgeDef; emphasis: Emphasis }) {
  const color = edge.dashed ? 'var(--vault-muted)' : 'var(--vault-accent)'
  return (
    <g>
      <mask id={id} maskUnits="userSpaceOnUse" x="-20" y="0" width="930" height="320">
        <path data-draw d={edge.d} fill="none" stroke="white" strokeWidth="16" strokeLinecap="round" />
      </mask>
      <path
        d={edge.d}
        fill="none"
        strokeWidth={emphasis === 'active' ? 2.4 : 1.5}
        strokeDasharray={edge.dashed ? '5 5' : undefined}
        stroke={emphasis === 'active' ? 'var(--vault-accent)' : color}
        markerEnd={emphasis === 'active' || !edge.dashed ? 'url(#arrow-accent)' : 'url(#arrow-muted)'}
        mask={`url(#${id})`}
        className="transition-[opacity,stroke-width] duration-200"
        style={{ opacity: emphasis === 'dim' ? 0.2 : 1 }}
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
    <g data-node={node.id}>
      <g
        tabIndex={0}
        role="img"
        aria-label={`${node.label}: ${node.detail}`}
        onPointerEnter={() => onHover(node.id)}
        onPointerLeave={() => onHover(null)}
        onFocus={() => onHover(node.id)}
        onBlur={() => onHover(null)}
        className="cursor-default transition-opacity duration-200 outline-none"
        style={{ opacity: emphasis === 'dim' ? 0.35 : 1 }}
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
    <figure data-lifecycle className="hidden rounded-xl border bg-card p-6 shadow-soft md:block lg:p-8">
      <svg
        viewBox="0 24 890 266"
        overflow="visible"
        className="mx-auto h-auto w-full max-w-5xl"
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
            fillOpacity="0.12"
            stroke="var(--vault-accent)"
            strokeOpacity="0.4"
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
        <text
          data-exception-label
          x="530"
          y="140"
          fill="var(--vault-muted)"
          className="text-[10.5px]"
          stroke="var(--card)"
          strokeWidth={5}
          paintOrder="stroke"
        >
          release
        </text>
        <text
          data-exception-label
          x="600"
          y="285"
          fill="var(--vault-muted)"
          className="text-[10.5px]"
          stroke="var(--card)"
          strokeWidth={5}
          paintOrder="stroke"
        >
          refund
        </text>
      </svg>
      <figcaption className="mt-6 min-h-10 border-t pt-4 text-sm text-muted-foreground" aria-live="polite">
        {detail ? (
          <>
            <span className="font-medium text-foreground">{detail.label}.</span> {detail.detail}
          </>
        ) : (
          <span className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <span className="inline-flex items-center gap-2">
              <span aria-hidden className="h-0.5 w-6 rounded bg-vault-accent" />
              Normal path
            </span>
            <span className="inline-flex items-center gap-2">
              <span aria-hidden className="w-6 border-t-2 border-dashed border-vault-muted" />
              Exception path
            </span>
            <span>States match the escrow contract on Stellar.</span>
          </span>
        )}
      </figcaption>
    </figure>
  )
}

/**
 * The scroll story: the states light up left to right while a ring follows the bounty along the normal path and
 * each arrow draws; then the exception paths draw in. It only touches the outer node groups, the mask strokes, the
 * ring and the labels, never what the hover emphasis styles.
 */
function buildTimeline({ gsap }: ScrollStoryTools, root: HTMLElement) {
  const q = gsap.utils.selector(root)
  const nodes = q('[data-node]')
  const mainMasks = q('[data-main] [data-draw]')
  const exceptionMasks = q('[data-exception] [data-draw]')
  const labels = q('[data-exception-label]')
  const current = q('[data-current]')

  gsap.set([...mainMasks, ...exceptionMasks], { drawSVG: '0%' })
  gsap.set(nodes, { autoAlpha: 0.14 })
  gsap.set(labels, { autoAlpha: 0 })
  gsap.set(current, { autoAlpha: 0, x: 0 })

  const tl = gsap.timeline({ defaults: { ease: 'none' } })
  tl.to([nodes[0], ...current], { autoAlpha: 1, duration: 0.3 }, 0)
  for (let i = 0; i < 4; i++) {
    tl.to(mainMasks[i], { drawSVG: '100%', duration: 0.6 }, i + 0.35)
      .to(current, { x: (i + 1) * STRIDE, duration: 0.6, ease: 'power2.inOut' }, i + 0.35)
      .to(nodes[i + 1], { autoAlpha: 1, duration: 0.3 }, i + 0.7)
  }
  tl.to(exceptionMasks, { drawSVG: '100%', duration: 1, stagger: 0.15 }, 4.4)
    .to(nodes.slice(5), { autoAlpha: 1, duration: 0.4, stagger: 0.15 }, 4.8)
    .to(labels, { autoAlpha: 1, duration: 0.4 }, 5.2)
    // A short hold with everything drawn before the section scrolls on.
    .to({}, { duration: 0.8 })
  return tl
}

const HEADING = {
  title: 'What happens to the money',
  description:
    'Rewards sit in a Soroban smart contract on Stellar, not in a BountyFlow bank account. The contract only moves funds along the paths below.',
}

/**
 * What happens to the money: the escrow state machine as a diagram whose states explain themselves on hover or
 * focus, the steps a reward goes through, and the guarantees that hold throughout. On wider screens with motion,
 * the diagram stays in view and draws itself as you scroll.
 */
export function EscrowExplainer() {
  const [hovered, setHovered] = useState<StateId | null>(null)
  const story = useScrollStoryEnabled('768px')
  const wrapper = useRef<HTMLDivElement>(null)
  useScrollStory(wrapper, story, buildTimeline)

  const diagram = (
    <>
      <SectionHeading id="escrow-title" {...HEADING} />
      <div className="mt-8">
        <Lifecycle hovered={hovered} onHover={setHovered} />
      </div>
    </>
  )

  return (
    <section id="escrow" aria-labelledby="escrow-title" className={SECTION}>
      {story ? (
        // A tall wrapper with a sticky stage: the diagram stays on screen while the wrapper scrolls past.
        <div ref={wrapper} data-escrow-story className="relative">
          <div className="sticky top-20">
            <PageContainer className="w-full">{diagram}</PageContainer>
          </div>
          <div aria-hidden style={{ height: '150svh' }} />
        </div>
      ) : (
        <PageContainer>{diagram}</PageContainer>
      )}

      <PageContainer>
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <div className="rounded-xl border bg-card shadow-soft">
            <h3 id="escrow-path" className="border-b px-5 py-4 text-[0.9375rem] font-semibold">
              The path of a reward
            </h3>
            <ol aria-labelledby="escrow-path" className="divide-y px-5">
              {STEPS.map(([title, text], i) => (
                <li key={title} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 py-4">
                  <span className="amount text-sm text-primary">{i + 1}</span>
                  <div>
                    <p className="text-sm font-medium">{title}</p>
                    <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
          <div className="rounded-xl border bg-card shadow-soft">
            <h3 id="escrow-guarantees" className="border-b px-5 py-4 text-[0.9375rem] font-semibold">
              What you can rely on
            </h3>
            <dl aria-labelledby="escrow-guarantees" className="divide-y px-5">
              {GUARANTEES.map(([title, text]) => (
                <div key={title} className="py-4">
                  <dt className="flex items-center gap-3 text-sm font-medium">
                    <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden />
                    {title}
                  </dt>
                  <dd className="mt-1 pl-7 text-sm leading-relaxed text-muted-foreground">{text}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </PageContainer>
    </section>
  )
}
