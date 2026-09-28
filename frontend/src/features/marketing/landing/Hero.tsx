import { ArrowRight, ExternalLink, LockKeyhole, PenLine, SearchCheck, type LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { DeadlineCountdown } from '@/components/bounty/DeadlineCountdown'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { Scene } from '@/components/three/Scene'
import { PageContainer } from '@/components/layout/PageContainer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { motionAllowed, useReducedMotion } from '@/hooks/useReducedMotion'
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

/** What makes a bounty here different, in three short facts under the actions. */
const FACTS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: LockKeyhole, title: 'Escrow first', text: 'The reward is locked before work starts.' },
  { icon: PenLine, title: 'Non-custodial', text: 'You sign every transfer in your own wallet.' },
  { icon: SearchCheck, title: 'Verifiable', text: 'Payouts and refunds are public on Stellar.' },
]

/** The lifecycle a bounty moves through, and where each status sits on it. */
const STAGES = ['Published', 'Funded', 'In progress', 'In review', 'Paid out'] as const
const STAGE_OF: Partial<Record<BountyStatus, number>> = {
  OPEN: 0,
  FUNDING_PENDING: 0,
  FUNDED: 1,
  IN_PROGRESS: 2,
  UNDER_REVIEW: 3,
  COMPLETED: 4,
}

/** True one frame after mount, so CSS transitions run from their initial state. */
function useAfterMount(): boolean {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    const frame = requestAnimationFrame(() => setReady(true))
    return () => cancelAnimationFrame(frame)
  }, [])
  return ready
}

/** Counts from zero to `value` when the card appears, then shows the exact figure. */
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

function Amount({ value, className }: { value: string; className?: string }) {
  const counting = useCountUp(Number(value))
  return (
    <span className={cn('amount', className)}>
      {counting === null ? formatAmount(value) : Math.round(counting).toLocaleString('en-US')}
    </span>
  )
}

function Lifecycle({ status }: { status: BountyStatus }) {
  const current = STAGE_OF[status] ?? 0
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
              style={{ transitionDelay: `${150 + i * 120}ms` }}
            />
            {i === current && <span className="bf-flow absolute inset-0 rounded-full" />}
          </span>
          <span
            className={cn(
              'mt-1.5 block truncate text-[0.6875rem]',
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

/** A live bounty (the largest open reward) as it appears in the product: reward, escrow and where it stands. */
function BountyPreview({ bounty }: { bounty: BountySummary }) {
  const href = `/bounties/${bounty.slug || bounty.id}`
  const positions = bounty.positions_available
  return (
    <article
      aria-labelledby="hero-bounty-title"
      className="relative animate-in rounded-2xl border bg-card p-5 shadow-lift duration-500 ease-out fade-in-0 slide-in-from-bottom-2 sm:p-6"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{CATEGORY_LABELS[bounty.category]}</Badge>
          <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
        </div>
        <DeadlineCountdown deadline={bounty.application_deadline} className="text-xs" />
      </div>

      <h2 id="hero-bounty-title" className="mt-4 text-base leading-snug font-semibold">
        <Link to={href} className="hover:underline">
          {bounty.title}
        </Link>
      </h2>
      <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
        <UserAvatar user={bounty.requester} className="size-5" />
        <span className="truncate">{bounty.requester.display_name}</span>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border">
        <div className="bg-surface/60 px-4 py-3">
          <dt className="text-xs text-muted-foreground">
            {positions > 1 ? 'Reward per position' : 'Reward'}
          </dt>
          <dd className="mt-1">
            <Amount value={bounty.reward_amount} className="text-[1.375rem]" />{' '}
            <span className="text-sm text-muted-foreground">{bounty.reward_asset.code}</span>
          </dd>
        </div>
        {positions > 1 ? (
          <div className="bg-surface/60 px-4 py-3">
            <dt className="text-xs text-muted-foreground">Escrow for {positions} positions</dt>
            <dd className="mt-1">
              <Amount value={bounty.total_reward} className="text-[1.375rem]" />{' '}
              <span className="text-sm text-muted-foreground">{bounty.reward_asset.code}</span>
            </dd>
          </div>
        ) : (
          <div className="bg-surface/60 px-4 py-3">
            <dt className="text-xs text-muted-foreground">Applicants</dt>
            <dd className="mt-1">
              <span className="amount text-[1.375rem]">{bounty.applications_count}</span>{' '}
              <span className="text-sm text-muted-foreground">so far</span>
            </dd>
          </div>
        )}
      </dl>

      <div className="mt-5">
        <Lifecycle status={bounty.status} />
      </div>

      <div className="mt-5 space-y-3 border-t pt-4">
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
    <div className="rounded-2xl border bg-card p-6 shadow-lift" aria-hidden>
      <div className="flex gap-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-24" />
      </div>
      <Skeleton className="mt-5 h-5 w-4/5" />
      <Skeleton className="mt-3 h-4 w-1/3" />
      <Skeleton className="mt-6 h-20 w-full rounded-xl" />
      <Skeleton className="mt-6 h-8 w-full" />
      <Skeleton className="mt-6 h-9 w-full" />
    </div>
  )
}

/** Two faded cards behind the preview, so it reads as the top of a stack of open bounties. */
function Stack() {
  return (
    <>
      <div
        aria-hidden
        className="absolute inset-x-5 top-4 -bottom-3 rounded-2xl border bg-card/70 shadow-soft"
      />
      <div aria-hidden className="absolute inset-x-10 top-8 -bottom-6 rounded-2xl border bg-card/40" />
    </>
  )
}

function Preview() {
  const { data, isPending, isError } = useBounties(TOP_REWARDS)
  const items = data?.items ?? []
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)
  const reduced = useReducedMotion()
  const count = items.length
  const current = count > 0 ? items[index % count] : undefined

  // Move to the next bounty every few seconds, unless the visitor is reading or pointing at this one.
  useEffect(() => {
    if (count < 2 || paused || reduced) return
    const timer = window.setTimeout(() => setIndex((i) => (i + 1) % count), ROTATE_MS)
    return () => window.clearTimeout(timer)
  }, [index, count, paused, reduced])

  if (isError) return null
  if (!isPending && !current) {
    return (
      <div className="rounded-2xl border border-dashed bg-card p-8 text-center">
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
  return (
    <div
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <Bones name="landing-hero-bounty" loading={isPending} fallback={<PreviewFallback />}>
        {current && (
          <div className="relative">
            {count > 1 && <Stack />}
            <BountyPreview key={current.id} bounty={current} />
          </div>
        )}
      </Bones>
      {count > 1 && (
        <div className="mt-8 flex items-center justify-center gap-2" role="group" aria-label="Open bounties">
          {items.map((b, i) => {
            const active = i === index % count
            return (
              <button
                key={b.id}
                type="button"
                onClick={() => setIndex(i)}
                aria-label={`Show ${b.title}`}
                aria-pressed={active}
                className="group flex h-6 items-center"
              >
                <span className="relative block h-1 w-8 overflow-hidden rounded-full bg-border transition-colors group-hover:bg-muted-foreground/40">
                  {active && (
                    <span
                      key={`${b.id}-${index}`}
                      className={cn('absolute inset-0 rounded-full bg-primary', !reduced && 'bf-progress')}
                      style={{
                        ['--bf-progress-duration' as string]: `${ROTATE_MS}ms`,
                        animationPlayState: paused ? 'paused' : 'running',
                      }}
                    />
                  )}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function Hero() {
  const wide = useMediaQuery('(min-width: 1024px)')
  return (
    <section aria-labelledby="hero-title" className="relative isolate overflow-hidden border-b">
      {/* A faint wash of the brand colour behind the top of the page. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[34rem] bg-[radial-gradient(60%_60%_at_50%_0%,color-mix(in_oklab,var(--primary)_9%,transparent),transparent)]"
      />
      <PageContainer className="grid items-center gap-12 py-16 sm:py-20 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:gap-16 lg:py-24">
        <div className="max-w-2xl">
          <h1
            id="hero-title"
            className="font-display text-[2.25rem] leading-[1.08] sm:text-[2.75rem] lg:text-[3.25rem]"
          >
            Bounties with the reward held in escrow
          </h1>
          <p className="mt-5 max-w-xl text-[1.0625rem] leading-relaxed text-muted-foreground">
            Post a task with a reward in XLM. The reward is locked in a Soroban escrow contract on Stellar
            before anyone starts, and it is released to the contributor when you approve the work.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg">
              <Link to="/bounties">Browse bounties</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link to="/app/bounties/create">Post a bounty</Link>
            </Button>
          </div>
          <dl className="mt-10 grid gap-5 border-t pt-6 sm:grid-cols-3 sm:gap-6">
            {FACTS.map(({ icon: Icon, title, text }) => (
              <div key={title}>
                <dt className="flex items-center gap-2 text-sm font-medium">
                  <Icon className="size-4 shrink-0 text-primary" aria-hidden />
                  {title}
                </dt>
                <dd className="mt-1 text-[0.8125rem] leading-snug text-muted-foreground">{text}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="relative w-full max-w-lg lg:justify-self-end">
          {wide && (
            <Scene
              name="globe"
              className="pointer-events-none absolute top-1/2 left-1/2 -z-10 size-[46rem] -translate-x-1/2 -translate-y-1/2 animate-in mask-[radial-gradient(closest-side,black_60%,transparent)] duration-1000 fade-in-0"
            />
          )}
          <Preview />
        </div>
      </PageContainer>
    </section>
  )
}
