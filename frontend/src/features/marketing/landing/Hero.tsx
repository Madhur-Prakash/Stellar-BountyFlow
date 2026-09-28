import {
  ArrowRight,
  BadgeCheck,
  ExternalLink,
  Hammer,
  LockKeyhole,
  Megaphone,
  PenLine,
  ScanSearch,
  SearchCheck,
  type LucideIcon,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from 'react'
import { Link } from 'react-router'

import { BountyStatusBadge } from '@/components/bounty/BountyStatusBadge'
import { DeadlineCountdown } from '@/components/bounty/DeadlineCountdown'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { PageContainer } from '@/components/layout/PageContainer'
import { AppWindow } from '@/components/marketing/AppWindow'
import { Atmosphere } from '@/components/marketing/Atmosphere'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { motionAllowed, useReducedMotion } from '@/hooks/useReducedMotion'
import {
  useScrollStory,
  useScrollStoryEnabled,
  useStageTop,
  type ScrollStoryTools,
} from '@/hooks/useScrollStory'
import { useBounties } from '@/lib/api/queries/bounties'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { BountyStatus, BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'
import { cn } from '@/lib/utils'

/** The three largest open rewards; the preview cycles through them. */
const TOP_REWARDS = { sort: 'reward_high', page_size: 3 } as const
const ROTATE_MS = 6000

/** What makes a bounty here different, in three short facts under the board. */
const FACTS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: LockKeyhole, title: 'Escrow first', text: 'The reward is locked before work starts.' },
  { icon: PenLine, title: 'Non-custodial', text: 'You sign every transfer in your own wallet.' },
  { icon: SearchCheck, title: 'Verifiable', text: 'Payouts and refunds are public on Stellar.' },
]

/** The lifecycle a bounty moves through, and where each status sits on it. */
const STAGES = ['Published', 'Funded', 'In progress', 'In review', 'Paid out'] as const
const LAST_STAGE = STAGES.length - 1
const STAGE_OF: Partial<Record<BountyStatus, number>> = {
  OPEN: 0,
  FUNDING_PENDING: 0,
  FUNDED: 1,
  IN_PROGRESS: 2,
  UNDER_REVIEW: 3,
  COMPLETED: 4,
}

/** The board's columns: the statuses each one lists, its icon, and what it says when nothing real is in it. */
const COLUMNS: { statuses: BountyStatus[]; icon: LucideIcon; empty: string }[] = [
  { statuses: ['OPEN', 'FUNDING_PENDING'], icon: Megaphone, empty: 'No other open bounties' },
  { statuses: ['FUNDED'], icon: LockKeyhole, empty: 'None funded yet' },
  { statuses: ['IN_PROGRESS'], icon: Hammer, empty: 'None in progress' },
  { statuses: ['UNDER_REVIEW'], icon: ScanSearch, empty: 'None in review' },
  { statuses: ['COMPLETED'], icon: BadgeCheck, empty: 'None paid out yet' },
]

/** True one frame after mount, so CSS transitions run from their initial state. */
function useAfterMount(): boolean {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    const frame = requestAnimationFrame(() => setReady(true))
    return () => cancelAnimationFrame(frame)
  }, [])
  return ready
}

/** Counts from zero to `value` when it first appears, then shows the exact figure. */
function useCountUp(value: number, duration = 900): number | null {
  const [shown, setShown] = useState<number | null>(() => (motionAllowed() ? 0 : null))
  useEffect(() => {
    if (!motionAllowed() || !Number.isFinite(value)) return
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - (1 - t) ** 3
      setShown(t < 1 ? value * eased : null)
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value, duration])
  return shown
}

function Amount({ value }: { value: string }) {
  const counting = useCountUp(Number(value))
  return <>{counting === null ? formatAmount(value) : Math.round(counting).toLocaleString('en-US')}</>
}

function Lifecycle({ current }: { current: number }) {
  const ready = useAfterMount()
  return (
    <ol className="grid grid-cols-5 gap-1.5" aria-label="Lifecycle">
      {STAGES.map((stage, i) => (
        <li key={stage} aria-current={i === current ? 'step' : undefined} className="min-w-0">
          <span aria-hidden className="relative block h-1 overflow-hidden rounded-full bg-muted">
            <span
              className={cn(
                'absolute inset-0 origin-left rounded-full bg-primary transition-transform duration-500 ease-out',
                ready && i <= current ? 'scale-x-100' : 'scale-x-0',
              )}
              style={{ transitionDelay: ready ? `${i * 80}ms` : `${150 + i * 120}ms` }}
            />
            {i === current && <span className="bf-flow absolute inset-0 rounded-full" />}
          </span>
          <span
            className={cn(
              'mt-1.5 block truncate text-[0.6875rem] transition-colors duration-300',
              i === current ? 'font-medium text-foreground' : 'text-muted-foreground',
            )}
          >
            {stage}
          </span>
        </li>
      ))}
    </ol>
  )
}

function ContractRow() {
  const { data } = usePublicConfig()
  if (!data?.contract_id) return null
  const href = data.contract_explorer_url ?? contractExplorerUrl(data, data.contract_id)
  const short = `${data.contract_id.slice(0, 6)}…${data.contract_id.slice(-6)}`
  return (
    <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
      <span>Escrow contract on {networkDisplayName(data.network, data.blockchain_mode)}</span>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Escrow contract ${data.contract_id} on the Stellar explorer`}
          className="inline-flex items-center gap-1 font-mono text-foreground hover:underline"
        >
          {short}
          <ExternalLink className="size-3" aria-hidden />
        </a>
      ) : (
        <span className="font-mono text-foreground">{short}</span>
      )}
    </div>
  )
}

type Cell = { label: string; figure?: ReactNode; unit?: string; text?: string; fill?: number }
type StageView = { badge: ReactNode; cells: [Cell, Cell]; caption: string }

/**
 * What the card shows at each stage of the lifecycle. Stage 0 is this bounty as it is now; later stages describe
 * what will happen to it ("When funded, …"), using its own reward, so the card never claims a state it isn't in.
 */
function stageView(b: BountySummary, stage: number, realStage: number): StageView {
  const code = b.reward_asset.code
  const total = formatAmount(b.total_reward)
  const per = formatAmount(b.reward_amount)
  const positions = b.positions_available
  const real = stage <= realStage
  switch (stage) {
    case 1:
      return {
        badge: <FundingStatusBadge status="FUNDED" bountyStatus="FUNDED" />,
        cells: [
          { label: 'In escrow', figure: total, unit: code, fill: 100 },
          { label: 'Held by', text: 'Soroban escrow contract' },
        ],
        caption: real
          ? `The full ${total} ${code} is locked in the escrow contract.`
          : `When funded, the full ${total} ${code} is locked in the escrow contract.`,
      }
    case 2:
      return {
        badge: <BountyStatusBadge status="IN_PROGRESS" />,
        cells: [
          { label: 'Reward locked', figure: total, unit: code },
          { label: 'Positions', text: `${positions} of ${positions} filled` },
        ],
        caption: 'Once a contributor is accepted, they do the work while the reward stays locked.',
      }
    case 3:
      return {
        badge: <BountyStatusBadge status="UNDER_REVIEW" />,
        cells: [
          { label: 'Submission', text: 'Awaiting review' },
          { label: 'Decision', text: 'Approve, revise or reject' },
        ],
        caption: 'The requester checks the submission against the acceptance criteria.',
      }
    case 4:
      return {
        badge: <BountyStatusBadge status="COMPLETED" />,
        cells: [
          { label: positions > 1 ? 'Paid per position' : 'Paid to contributor', figure: per, unit: code },
          { label: 'Proof', text: 'Public transaction hash' },
        ],
        caption: `On approval, the contract pays ${per} ${code} straight to the contributor's verified wallet.`,
      }
    default:
      return {
        badge: <FundingStatusBadge status={b.funding_status} bountyStatus={b.status} />,
        cells: [
          {
            label: positions > 1 ? 'Reward per position' : 'Reward',
            figure: <Amount value={b.reward_amount} />,
            unit: code,
          },
          positions > 1
            ? {
                label: `Escrow for ${positions} positions`,
                figure: <Amount value={b.total_reward} />,
                unit: code,
              }
            : { label: 'Applicants', figure: String(b.applications_count), unit: 'so far' },
        ],
        caption: 'Published and taking applications.',
      }
  }
}

function StageCell({ cell }: { cell: Cell }) {
  return (
    <div className="bg-surface/70 px-4 py-3 dark:bg-background/40">
      <dt className="text-xs text-muted-foreground">{cell.label}</dt>
      <dd className="mt-1 flex min-h-8 items-baseline gap-1.5">
        {cell.figure !== undefined ? (
          <>
            <span className="amount text-[1.375rem]">{cell.figure}</span>
            {cell.unit && <span className="text-sm text-muted-foreground">{cell.unit}</span>}
          </>
        ) : (
          <span className="self-center text-sm font-medium">{cell.text}</span>
        )}
      </dd>
      {cell.fill !== undefined && (
        <span aria-hidden className="mt-2 block h-1 overflow-hidden rounded-full bg-muted">
          <span className="block h-full animate-in rounded-full bg-success duration-700 slide-in-from-left" />
        </span>
      )}
    </div>
  )
}

/**
 * A live bounty (one of the largest open rewards) as it appears in the product: reward, escrow and where it
 * stands. In the scroll story, `stage` walks it through the lifecycle.
 */
function BountyPreview({ bounty, stage }: { bounty: BountySummary; stage: number | null }) {
  const href = `/bounties/${bounty.slug || bounty.id}`
  const realStage = STAGE_OF[bounty.status] ?? 0
  const shown = stage === null ? realStage : Math.max(realStage, stage)
  const view = stageView(bounty, shown, realStage)
  return (
    <article
      aria-labelledby="hero-bounty-title"
      className="relative animate-in rounded-xl border border-primary/30 bg-card p-4 text-left shadow-lift ring-1 ring-primary/10 duration-500 ease-out fade-in-0 slide-in-from-bottom-2 sm:p-5 dark:border-primary/45 dark:bg-surface-raised"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{CATEGORY_LABELS[bounty.category]}</Badge>
          <span key={shown} className="animate-in duration-300 fade-in-0">
            {view.badge}
          </span>
        </div>
        {shown > realStage ? (
          <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
            Stage {shown + 1} of {STAGES.length}
          </span>
        ) : (
          <DeadlineCountdown deadline={bounty.application_deadline} className="text-xs whitespace-nowrap" />
        )}
      </div>

      <h2 id="hero-bounty-title" className="mt-3.5 text-base leading-snug font-semibold">
        <Link to={href} className="hover:underline">
          {bounty.title}
        </Link>
      </h2>
      <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
        <UserAvatar user={bounty.requester} className="size-5" />
        <span className="truncate">{bounty.requester.display_name}</span>
      </div>

      <dl
        key={shown}
        className="mt-4 grid animate-in grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border duration-300 fade-in-0 slide-in-from-bottom-1"
      >
        <StageCell cell={view.cells[0]} />
        <StageCell cell={view.cells[1]} />
      </dl>

      <div className="mt-4">
        <Lifecycle current={shown} />
        <p
          key={shown}
          className="mt-3 min-h-10 animate-in text-xs leading-relaxed text-muted-foreground duration-300 fade-in-0"
        >
          {view.caption}
        </p>
      </div>

      <div className="mt-2 space-y-3 border-t pt-3.5">
        <ContractRow />
        <Button asChild variant="outline" className="w-full">
          <Link to={href}>
            View this bounty <ArrowRight aria-hidden />
          </Link>
        </Button>
      </div>
    </article>
  )
}

function PreviewFallback() {
  return (
    <div className="rounded-xl border bg-card p-5 shadow-lift dark:bg-surface-raised" aria-hidden>
      <div className="flex gap-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-24" />
      </div>
      <Skeleton className="mt-5 h-5 w-4/5" />
      <Skeleton className="mt-3 h-4 w-1/3" />
      <Skeleton className="mt-5 h-20 w-full rounded-lg" />
      <Skeleton className="mt-5 h-8 w-full" />
      <Skeleton className="mt-5 h-4 w-full" />
      <Skeleton className="mt-4 h-9 w-full" />
    </div>
  )
}

function NoOpenBounties() {
  return (
    <div className="rounded-xl border border-dashed bg-card p-8 text-center dark:bg-surface-raised">
      <p className="font-medium">No open bounties right now</p>
      <p className="mt-1 text-sm text-muted-foreground">
        Post the first one: describe the work, set a reward and fund it from your wallet.
      </p>
      <Button asChild size="sm" className="mt-4">
        <Link to="/app/bounties/create">Post a bounty</Link>
      </Button>
    </div>
  )
}

/** One real bounty in a board column: its title, category and reward. */
function BoardRow({ bounty }: { bounty: BountySummary }) {
  return (
    <li>
      <Link
        to={`/bounties/${bounty.slug || bounty.id}`}
        className="block rounded-lg border bg-background px-3 py-2.5 transition-colors hover:border-foreground/20 dark:bg-surface-raised"
      >
        <span className="line-clamp-2 text-[0.8125rem] leading-snug font-medium">{bounty.title}</span>
        <span className="mt-2 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <span className="min-w-0 truncate">{CATEGORY_LABELS[bounty.category]}</span>
          <span className="shrink-0">
            <span className="amount text-foreground">{formatAmount(bounty.reward_amount)}</span>{' '}
            {bounty.reward_asset.code}
          </span>
        </span>
      </Link>
    </li>
  )
}

/**
 * One stage of the board with the real bounties in it (the live card's own bounty aside). A stage with nothing
 * real in it says so quietly; the column holding the live card leaves its first slot to the card.
 */
function BoardColumn({
  index,
  active,
  grow,
  excludeId,
}: {
  index: number
  active: boolean
  grow: number
  excludeId?: string
}) {
  const column = COLUMNS[index]
  const { data, isPending } = useBounties({ status: column.statuses, sort: 'newest', page_size: 5 })
  const rows = (data?.items ?? []).filter((b) => b.id !== excludeId).slice(0, 4)
  const Icon = column.icon
  return (
    <div
      className="flex min-w-0 basis-0 flex-col border-l px-2 transition-[flex-grow] duration-500 ease-[cubic-bezier(0.22,0.8,0.2,1)] first:border-l-0"
      style={{ flexGrow: grow }}
    >
      <p className="flex h-10 shrink-0 items-center gap-2 px-1 text-[0.8125rem]">
        <Icon
          aria-hidden
          className={cn(
            'size-3.5 shrink-0 transition-colors duration-300',
            active ? 'text-primary-emphasis' : 'text-muted-foreground',
          )}
        />
        <span
          className={cn(
            'truncate transition-colors duration-300',
            active ? 'font-medium text-foreground' : 'text-muted-foreground',
          )}
        >
          {STAGES[index]}
        </span>
        {data && (
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            {data.total}
            <span className="sr-only"> {data.total === 1 ? 'bounty' : 'bounties'}</span>
          </span>
        )}
      </p>
      <div
        className="min-h-0 transition-[padding-top] duration-500 ease-[cubic-bezier(0.22,0.8,0.2,1)]"
        style={{ paddingTop: active ? 'calc(var(--card-h) + 0.625rem)' : 0 }}
      >
        {isPending ? (
          <div className="space-y-2" aria-hidden>
            <Skeleton className="h-16 w-full rounded-lg" />
            <Skeleton className="h-16 w-full rounded-lg" />
          </div>
        ) : rows.length > 0 ? (
          <ul aria-label={STAGES[index]} className="space-y-2">
            {rows.map((b) => (
              <BoardRow key={b.id} bounty={b} />
            ))}
          </ul>
        ) : (
          !active && (
            <p className="rounded-lg border border-dashed px-3 py-3 text-xs leading-snug text-muted-foreground">
              {column.empty}
            </p>
          )
        )}
      </div>
    </div>
  )
}

/** Card width the board aims for, and how much of the column below the card stays visible. */
const CARD_MIN = 372
const CARD_MAX = 452
const PEEK = 76

/**
 * The board on large screens: one column per stage, and the live card sitting in the column of the stage it is
 * showing. When the stage changes, that column opens up and the card glides into it.
 */
function Board({ active, card, excludeId }: { active: number; card: ReactNode; excludeId?: string }) {
  const board = useRef<HTMLDivElement>(null)
  const slot = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 1200, card: 430 })

  useLayoutEffect(() => {
    const el = board.current
    const cardEl = slot.current
    if (!el || !cardEl) return
    const measure = () =>
      setSize((s) => {
        const next = { width: el.clientWidth, card: cardEl.offsetHeight }
        return next.width === s.width && next.card === s.card ? s : next
      })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    ro.observe(cardEl)
    return () => ro.disconnect()
  }, [])

  // The card's column is wide enough for the card; the other four share the rest.
  const cardWidth = Math.min(CARD_MAX, Math.max(CARD_MIN, size.width * 0.36)) + 16
  const wide = Math.max(1.5, (cardWidth * 4) / Math.max(1, size.width - cardWidth))
  const units = 4 + wide
  const style = { '--card-h': `${size.card}px` } as CSSProperties

  return (
    <div
      ref={board}
      style={{
        ...style,
        height: 40 + size.card + PEEK,
        maskImage: 'linear-gradient(to bottom, black calc(100% - 3.5rem), transparent)',
      }}
      className="relative flex overflow-hidden"
    >
      {COLUMNS.map((_, i) => (
        <BoardColumn
          key={i}
          index={i}
          active={i === active}
          grow={i === active ? wide : 1}
          excludeId={excludeId}
        />
      ))}
      <div
        ref={slot}
        className="absolute top-10 transition-[left] duration-500 ease-[cubic-bezier(0.22,0.8,0.2,1)]"
        style={{
          left: `calc(${(100 * active) / units}% + 0.5rem)`,
          width: `calc(${(100 * wide) / units}% - 1rem)`,
        }}
      >
        {card}
      </div>
    </div>
  )
}

/** The rotation between the top rewards: one bar per bounty, the current one filling while it is shown. */
function Picker({
  items,
  index,
  holding,
  onPick,
}: {
  items: BountySummary[]
  index: number
  holding: boolean
  onPick: (i: number) => void
}) {
  const reduced = useReducedMotion()
  const count = items.length
  if (count < 2) return null
  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="Open bounties">
      {items.map((b, i) => {
        const active = i === index % count
        return (
          <button
            key={b.id}
            type="button"
            onClick={() => onPick(i)}
            aria-label={`Show ${b.title}`}
            aria-pressed={active}
            className="group flex h-6 items-center"
          >
            <span className="relative block h-1 w-7 overflow-hidden rounded-full bg-border transition-colors group-hover:bg-muted-foreground/40">
              {active && (
                <span
                  key={`${b.id}-${index}`}
                  className={cn('absolute inset-0 rounded-full bg-primary', !reduced && 'bf-progress')}
                  style={{
                    ['--bf-progress-duration' as string]: `${ROTATE_MS}ms`,
                    animationPlayState: holding ? 'paused' : 'running',
                  }}
                />
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}

function NetworkName() {
  const { data } = usePublicConfig()
  if (!data) return null
  return (
    <span className="hidden font-mono text-xs font-normal text-muted-foreground sm:inline">
      Stellar {networkDisplayName(data.network, data.blockchain_mode)}
    </span>
  )
}

/**
 * The product window in the hero: the live bounty card and, on large screens, the board around it. `stage` is
 * the scroll story's stage (null when there is no story).
 */
function HeroWindow({ stage, board }: { stage: number | null; board: boolean }) {
  const { data, isPending, isError } = useBounties(TOP_REWARDS)
  const items = data?.items ?? []
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)
  const reduced = useReducedMotion()
  const count = items.length
  const current = count > 0 ? items[index % count] : undefined
  // Once the scroll story is walking a bounty through its lifecycle, keep that bounty on the card.
  const holding = paused || (stage ?? 0) > 0

  // Move to the next bounty every few seconds, unless the visitor is reading or pointing at this one.
  useEffect(() => {
    if (count < 2 || holding || reduced) return
    const timer = window.setTimeout(() => setIndex((i) => (i + 1) % count), ROTATE_MS)
    return () => window.clearTimeout(timer)
  }, [index, count, holding, reduced])

  const realStage = current ? (STAGE_OF[current.status] ?? 0) : 0
  const shown = stage === null ? realStage : Math.max(realStage, stage)

  const card = isError ? null : !isPending && !current ? (
    <NoOpenBounties />
  ) : (
    <div
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <Bones name="landing-hero-bounty" loading={isPending} fallback={<PreviewFallback />}>
        {current && <BountyPreview key={current.id} bounty={current} stage={stage} />}
      </Bones>
    </div>
  )

  return (
    <AppWindow
      title={
        <>
          <span>Bounty board</span>
          <NetworkName />
        </>
      }
      toolbar={<Picker items={items} index={index} holding={holding} onPick={setIndex} />}
      bodyClassName={board ? 'px-1.5' : 'p-3 sm:p-5'}
    >
      {board ? (
        <Board active={shown} card={card} excludeId={current?.id} />
      ) : (
        <div className="mx-auto max-w-xl">{card}</div>
      )}
    </AppWindow>
  )
}

/** The board's panel: the window on its atmospheric backdrop. */
function HeroPanel({
  stage,
  board,
  panelRef,
}: {
  stage: number | null
  board: boolean
  panelRef?: RefObject<HTMLDivElement | null>
}) {
  return (
    <div ref={panelRef}>
      <Atmosphere tone="dusk" className="px-3 py-4 sm:px-8 sm:py-10 xl:px-12 xl:py-14">
        <HeroWindow stage={stage} board={board} />
      </Atmosphere>
    </div>
  )
}

/** The hero story has no scrubbed tweens of its own; the card follows the reported progress. */
function buildHeroTimeline({ gsap }: ScrollStoryTools) {
  return gsap.timeline().to({}, { duration: 1 })
}

/**
 * The first screen: the headline and actions, then the product board on its backdrop. On large screens with
 * motion, the board stays in view for a short scroll while the live card walks its bounty through the lifecycle
 * (published → funded → in progress → in review → paid out), moving column to column. Elsewhere the card shows
 * the bounty as it is.
 */
export function Hero() {
  const story = useScrollStoryEnabled('1024px')
  const board = useMediaQuery('(min-width: 1024px)')
  const wrapper = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const [stage, setStage] = useState(0)
  const last = useRef(0)
  const onProgress = useCallback((p: number) => {
    const next = Math.min(LAST_STAGE, Math.floor(p * STAGES.length))
    if (next === last.current) return
    last.current = next
    setStage(next)
  }, [])
  // The board sticks centred under the header (at most 64px from the top), or bottom-aligned if it is taller.
  const top = useStageTop(panel, story, 64)
  useScrollStory(wrapper, story, buildHeroTimeline, onProgress, top)

  return (
    <section aria-labelledby="hero-title" className="relative isolate overflow-clip">
      <PageContainer className="pt-14 pb-12 text-center sm:pt-24 sm:pb-16 lg:pt-28">
        <h1
          id="hero-title"
          className="font-display mx-auto max-w-5xl text-[2.75rem] leading-[1.02] font-normal tracking-[-0.032em] sm:text-[4rem] lg:text-[4.75rem]"
        >
          Bounties with the reward held in escrow
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-[1.0625rem] leading-relaxed text-muted-foreground sm:text-xl sm:leading-relaxed">
          Post a task with a reward in XLM. It is locked in a Soroban contract on Stellar before work starts,
          and paid to the contributor when you approve.
        </p>
        <div className="mt-9 flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
          <Button asChild variant="inverse" size="pill">
            <Link to="/bounties">Browse bounties</Link>
          </Button>
          <Button asChild variant="outline" size="pill">
            <Link to="/app/bounties/create">Post a bounty</Link>
          </Button>
        </div>
      </PageContainer>

      <PageContainer>
        {story ? (
          <div ref={wrapper} data-hero-story>
            <div className="sticky" style={{ top }}>
              <HeroPanel stage={stage} board panelRef={panel} />
            </div>
            {/* Scroll room for the story (a sticky element can only travel through its parent's content). */}
            <div aria-hidden style={{ height: '200svh' }} />
          </div>
        ) : (
          <HeroPanel stage={null} board={board} />
        )}

        <dl className="mt-10 grid border-y sm:mt-14 sm:grid-cols-3">
          {FACTS.map(({ icon: Icon, title, text }) => (
            <div
              key={title}
              className="border-t px-1 py-6 first:border-t-0 sm:border-t-0 sm:border-l sm:px-8 sm:py-8 sm:first:border-l-0 sm:first:pl-1"
            >
              <dt className="flex items-center gap-2.5 text-[0.9375rem] font-medium">
                <Icon className="size-4 shrink-0 text-primary-emphasis" aria-hidden />
                {title}
              </dt>
              <dd className="mt-1.5 text-[0.9375rem] leading-relaxed text-muted-foreground">{text}</dd>
            </div>
          ))}
        </dl>
      </PageContainer>
    </section>
  )
}
