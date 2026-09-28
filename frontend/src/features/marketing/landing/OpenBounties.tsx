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

import { SECTION, SectionHeading } from './SectionHeading'

const SHOWN = 6

function Row({ bounty }: { bounty: BountySummary }) {
  const href = `/bounties/${bounty.slug || bounty.id}`
  return (
    <li className="group relative grid gap-3 px-5 py-4 transition-colors hover:bg-muted/40 md:grid-cols-[minmax(0,1fr)_9rem_8rem_9rem] md:items-center md:gap-6">
      <div className="min-w-0">
        <h3 className="truncate text-sm font-semibold">
          <Link to={href} className="outline-none after:absolute after:inset-0 focus-visible:underline">
            {bounty.title}
          </Link>
        </h3>
        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
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
          <span className="amount text-[0.9375rem]">{formatAmount(bounty.reward_amount)}</span>{' '}
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
        <li key={i} className="flex items-center gap-6 px-5 py-4">
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

/** Featured open bounties as a compact table: what the work is, who posted it, the reward and its escrow state. */
export function OpenBounties() {
  const { data, isPending, isError, error, refetch } = useFeaturedBounties()

  return (
    <section aria-labelledby="open-bounties-title" className={SECTION}>
      <PageContainer>
        <SectionHeading
          id="open-bounties-title"
          title="Open bounties"
          description="Work that is taking applications now."
          actions={
            <Button asChild variant="outline">
              <Link to="/bounties">
                View marketplace <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        />

        <div className="mt-8 overflow-hidden rounded-xl border bg-card shadow-soft">
          <div
            aria-hidden
            className="hidden border-b bg-surface px-5 py-2.5 text-xs font-medium text-muted-foreground md:grid md:grid-cols-[minmax(0,1fr)_9rem_8rem_9rem] md:gap-6"
          >
            <span>Bounty</span>
            <span>Funding</span>
            <span>Closes</span>
            <span className="text-right">Reward</span>
          </div>
          {isError ? (
            <div className="p-5">
              <ErrorState error={error} title="Open bounties could not be loaded" onRetry={() => refetch()} />
            </div>
          ) : !isPending && data.length === 0 ? (
            <div className="px-6 py-12 text-center">
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
