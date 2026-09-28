import { ArrowRight, ExternalLink, LockKeyhole, PenLine, SearchCheck, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'

import { DeadlineCountdown } from '@/components/bounty/DeadlineCountdown'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { PageContainer } from '@/components/layout/PageContainer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useBounties } from '@/lib/api/queries/bounties'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { BountyStatus, BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'
import { cn } from '@/lib/utils'

const TOP_REWARD = { sort: 'reward_high', page_size: 1 } as const

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

function Lifecycle({ status }: { status: BountyStatus }) {
  const current = STAGE_OF[status] ?? 0
  return (
    <ol className="grid grid-cols-5 gap-1.5" aria-label="Lifecycle">
      {STAGES.map((stage, i) => (
        <li key={stage} aria-current={i === current ? 'step' : undefined} className="min-w-0">
          <span
            aria-hidden
            className={cn('block h-1 rounded-full', i <= current ? 'bg-primary' : 'bg-muted')}
          />
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
      className="relative rounded-2xl border bg-card p-5 shadow-lift sm:p-6"
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
            <span className="amount text-[1.375rem]">{formatAmount(bounty.reward_amount)}</span>{' '}
            <span className="text-sm text-muted-foreground">{bounty.reward_asset.code}</span>
          </dd>
        </div>
        {positions > 1 ? (
          <div className="bg-surface/60 px-4 py-3">
            <dt className="text-xs text-muted-foreground">Escrow for {positions} positions</dt>
            <dd className="mt-1">
              <span className="amount text-[1.375rem]">{formatAmount(bounty.total_reward)}</span>{' '}
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

function Preview() {
  const { data, isPending, isError } = useBounties(TOP_REWARD)
  const bounty = data?.items[0]
  if (isError) return null
  if (!isPending && !bounty) {
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
    <Bones name="landing-hero-bounty" loading={isPending} fallback={<PreviewFallback />}>
      {bounty && <BountyPreview bounty={bounty} />}
    </Bones>
  )
}

export function Hero() {
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
        <div className="w-full max-w-lg lg:justify-self-end">
          <Preview />
        </div>
      </PageContainer>
    </section>
  )
}
