import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'

import { DeadlineCountdown } from '@/components/bounty/DeadlineCountdown'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useFeaturedBounties } from '@/lib/api/queries/bounties'
import type { BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

import { SectionHeading } from './SectionHeading'

const SHOWN = 6
const COLUMNS = 'md:grid-cols-[minmax(0,1fr)_10rem_8rem_9rem] md:gap-8'

function Row({ bounty }: { bounty: BountySummary }) {
  const href = `/bounties/${bounty.slug || bounty.id}`
  return (
    <li
      className={cn(
        'group relative grid gap-3 px-5 py-5 transition-colors hover:bg-surface/70 sm:px-7 md:items-center dark:hover:bg-white/2.5',
        COLUMNS,
      )}
    >
      <div className="min-w-0">
        <h3 className="truncate text-[0.9375rem] font-medium">
          <Link to={href} className="outline-none after:absolute after:inset-0 focus-visible:underline">
            {bounty.title}
          </Link>
        </h3>
        <div className="mt-1.5 flex items-center gap-2 text-[0.8125rem] text-muted-foreground">
          <UserAvatar user={bounty.requester} className="size-4" />
          <span className="truncate">{bounty.requester.display_name}</span>
          <span className="ml-2 shrink-0">
            {CATEGORY_LABELS[bounty.category]}, {DIFFICULTY_LABELS[bounty.difficulty].toLowerCase()}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-3 md:contents">
        <div className="md:justify-self-start">
          <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
        </div>
        <DeadlineCountdown deadline={bounty.application_deadline} className="text-xs text-muted-foreground" />
        <div className="ml-auto text-right md:ml-0">
          <span className="amount text-base">{formatAmount(bounty.reward_amount)}</span>{' '}
          <span className="text-xs text-muted-foreground">{bounty.reward_asset.code}</span>
        </div>
      </div>
    </li>
  )
}

function Fallback() {
  return (
    <ul className="divide-y" aria-hidden>
      {Array.from({ length: SHOWN }, (_, i) => (
        <li key={i} className="flex items-center gap-8 px-5 py-5 sm:px-7">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <Skeleton className="hidden h-5 w-24 md:block" />
          <Skeleton className="hidden h-4 w-20 md:block" />
          <Skeleton className="h-4 w-16" />
        </li>
      ))}
    </ul>
  )
}

/** Featured open bounties as a hairline table: what the work is, who posted it, the reward and its escrow state. */
export function OpenBounties() {
  const { data, isPending, isError, error, refetch } = useFeaturedBounties()

  return (
    <section aria-labelledby="open-bounties-title" className="pt-6 pb-16 sm:pt-8 sm:pb-24">
      <PageContainer>
        <SectionHeading
          id="open-bounties-title"
          label="Marketplace"
          title="Open bounties"
          description="Work that is taking applications now."
          actions={
            <Button asChild variant="outline" size="pill">
              <Link to="/bounties">
                View marketplace <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        />

        <div className="mt-10 overflow-hidden rounded-2xl border bg-card">
          <div
            aria-hidden
            className={cn(
              'hidden border-b bg-surface/60 px-7 py-3 font-mono text-xs text-muted-foreground md:grid dark:bg-white/2',
              COLUMNS,
            )}
          >
            <span>Bounty</span>
            <span>Funding</span>
            <span>Closes</span>
            <span className="text-right">Reward</span>
          </div>
          {isError ? (
            <div className="p-6">
              <ErrorState error={error} title="Open bounties could not be loaded" onRetry={() => refetch()} />
            </div>
          ) : !isPending && data.length === 0 ? (
            <div className="px-6 py-14 text-center">
              <p className="font-medium">No open bounties right now</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Post the first one: describe the work, set a reward, and fund it from your wallet.
              </p>
              <Button asChild size="sm" className="mt-4">
                <Link to="/app/bounties/create">Post a bounty</Link>
              </Button>
            </div>
          ) : (
            <Bones name="landing-open-bounties" loading={isPending} fallback={<Fallback />}>
              {data && (
                <ul aria-label="Open bounties list" className="divide-y">
                  {data.slice(0, SHOWN).map((b) => (
                    <Row key={b.id} bounty={b} />
                  ))}
                </ul>
              )}
            </Bones>
          )}
        </div>
      </PageContainer>
    </section>
  )
}
