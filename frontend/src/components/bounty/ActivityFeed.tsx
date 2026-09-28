import { Activity } from 'lucide-react'
import { useState } from 'react'

import { UserAvatar } from '@/components/common/UserAvatar'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { ListSkeleton } from '@/components/layout/LoadingState'
import { Button } from '@/components/ui/button'
import { useBountyActivity } from '@/lib/api/queries/bounties'
import { describeActivity, formatDateTime, formatRelative } from '@/lib/format'

/** Chronological activity for one bounty (GET /bounties/{id}/activity). */
export function ActivityFeed({ bountyId }: { bountyId: string }) {
  const [pageSize, setPageSize] = useState(10)
  const { data, isPending, isError, error, refetch, isFetching } = useBountyActivity(bountyId, {
    page: 1,
    page_size: pageSize,
  })

  if (isPending) return <ListSkeleton rows={3} />
  if (isError) return <ErrorState error={error} title="Activity unavailable" onRetry={() => refetch()} />
  if (data.items.length === 0) {
    return (
      <EmptyState
        icon={Activity}
        title="No activity yet"
        description="Events like publishing, funding, and reviews will appear here."
      />
    )
  }

  return (
    <div>
      <ol className="relative space-y-5 border-l pl-6">
        {data.items.map((item) => (
          <li key={item.id} className="relative">
            <span
              className="absolute top-1.5 -left-[29px] size-2.5 rounded-full border-2 border-background bg-muted-foreground"
              aria-hidden
            />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              {item.actor ? (
                <span className="inline-flex items-center gap-1.5 font-medium">
                  <UserAvatar user={item.actor} className="size-5" />
                  {item.actor.display_name}
                </span>
              ) : (
                <span className="font-medium">BountyFlow</span>
              )}
              <span className="text-muted-foreground">{describeActivity(item.action)}</span>
            </div>
            <time
              dateTime={item.created_at}
              title={formatDateTime(item.created_at)}
              className="text-xs text-muted-foreground"
            >
              {formatRelative(item.created_at)}
            </time>
          </li>
        ))}
      </ol>
      {data.total > data.items.length && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-4"
          disabled={isFetching}
          onClick={() => setPageSize((s) => Math.min(100, s + 20))}
        >
          {isFetching ? 'Loading…' : `Show more (${data.total - data.items.length} older)`}
        </Button>
      )}
    </div>
  )
}
