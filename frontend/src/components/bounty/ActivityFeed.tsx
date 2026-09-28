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
    return <EmptyState icon={Activity} title="No activity yet" className="border-0 bg-transparent py-6" />
  }

  return (
    <div>
      <ol className="divide-y">
        {data.items.map((item) => (
          <li key={item.id} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
            {item.actor ? (
              <UserAvatar user={item.actor} className="mt-px size-6" />
            ) : (
              <span
                className="mt-px flex size-6 shrink-0 items-center justify-center rounded-full border bg-surface text-muted-foreground"
                aria-hidden
              >
                <Activity className="size-3" />
              </span>
            )}
            <p className="min-w-0 flex-1 text-sm leading-6">
              <span className="font-medium">{item.actor ? item.actor.display_name : 'BountyFlow'}</span>{' '}
              <span className="text-muted-foreground">{describeActivity(item.action)}</span>
            </p>
            <time
              dateTime={item.created_at}
              title={formatDateTime(item.created_at)}
              className="shrink-0 text-xs leading-6 text-muted-foreground"
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
          className="mt-3 -ml-2 text-muted-foreground"
          disabled={isFetching}
          onClick={() => setPageSize((s) => Math.min(100, s + 20))}
        >
          {isFetching ? 'Loading…' : `Show ${data.total - data.items.length} older`}
        </Button>
      )}
    </div>
  )
}
