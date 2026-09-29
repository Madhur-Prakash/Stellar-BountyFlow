import { Compass } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyGridSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { BountyRow, BountyListSkeleton } from '@/components/bounty/BountyRow'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { Button } from '@/components/ui/button'
import type { Recommendation, RecommendationPage } from '@/lib/api/types'
import { cn } from '@/lib/utils'

import { reasonText } from './recommendation-reason'

function Reason({ recommendation, className }: { recommendation: Recommendation; className?: string }) {
  const text = reasonText(recommendation.reason)
  if (!text) return null
  return <p className={cn('text-xs text-muted-foreground', className)}>{text}</p>
}

/** "For you" results: the skill-graph ranking in the marketplace's grid or list, each with why it was picked. */
export function ForYouResults({
  query,
  view,
  narrowed,
  onClear,
  pagination,
}: {
  query: {
    data: RecommendationPage | undefined
    isPending: boolean
    isError: boolean
    error: unknown
    isPlaceholderData: boolean
    refetch: () => unknown
  }
  view: 'grid' | 'list'
  narrowed: boolean
  onClear: () => void
  pagination: (data: RecommendationPage) => ReactNode
}) {
  const { data, isPending, isError, error, isPlaceholderData, refetch } = query
  if (isError)
    return <ErrorState error={error} title="Could not load recommendations" onRetry={() => refetch()} />
  if (!isPending && data && data.items.length === 0) {
    if (!data.seed_skills.length) {
      return (
        <EmptyState
          icon={Compass}
          title="Add skills to get recommendations"
          description="Bounties are matched to the skills on your profile and the work you apply to."
          action={
            <Button asChild>
              <Link to="/app/profile">Add skills</Link>
            </Button>
          }
        />
      )
    }
    return (
      <EmptyState
        icon={Compass}
        title={narrowed ? 'No recommendations match these filters' : 'Nothing matches your skills right now'}
        description={
          narrowed
            ? 'Try fewer filters.'
            : `Based on ${data.seed_skills.slice(0, 5).join(', ')}. New bounties are matched as they are posted.`
        }
        action={
          narrowed ? (
            <Button variant="outline" onClick={onClear}>
              Clear filters
            </Button>
          ) : (
            <Button asChild variant="outline">
              <Link to="/app/profile">Edit skills</Link>
            </Button>
          )
        }
      />
    )
  }
  if (view === 'list') {
    return (
      <Bones name="marketplace-for-you-list" loading={isPending} fallback={<BountyListSkeleton count={8} />}>
        {data && (
          <>
            <div
              className={cn(
                '@container overflow-hidden rounded-xl border bg-card shadow-soft transition-opacity',
                isPlaceholderData && 'opacity-60',
              )}
            >
              <ul className="divide-y" aria-label="Recommended bounties">
                {data.items.map((r) => (
                  <li key={r.bounty.id}>
                    <BountyRow bounty={r.bounty} />
                    <Reason recommendation={r} className="-mt-1.5 px-4 pb-3 @3xl:px-5" />
                  </li>
                ))}
              </ul>
            </div>
            {pagination(data)}
          </>
        )}
      </Bones>
    )
  }
  return (
    <Bones name="marketplace-for-you" loading={isPending} fallback={<BountyGridSkeleton count={6} />}>
      {data && (
        <>
          <ul
            className={cn(
              'grid gap-4 transition-opacity sm:grid-cols-2 xl:grid-cols-3',
              isPlaceholderData && 'opacity-60',
            )}
            aria-label="Recommended bounties"
          >
            {data.items.map((r) =>
              reasonText(r.reason) ? (
                <li key={r.bounty.id} className="flex flex-col">
                  <BountyCard bounty={r.bounty} className="flex-1 rounded-b-none" />
                  <div className="rounded-b-xl border border-t-0 bg-surface/60 px-5 py-2.5">
                    <Reason recommendation={r} />
                  </div>
                </li>
              ) : (
                <li key={r.bounty.id}>
                  <BountyCard bounty={r.bounty} />
                </li>
              ),
            )}
          </ul>
          {pagination(data)}
        </>
      )}
    </Bones>
  )
}
