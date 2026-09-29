import { Link } from 'react-router'

import { Skeleton } from '@/components/ui/skeleton'
import type { BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

import { BookmarkButton } from './BookmarkButton'
import { applicantsLabel, bountyHref, openPositionsOf, questionsLabel } from './bounty-display'
import { BountyBadges } from './BountyCard'
import { DeadlineCountdown } from './DeadlineCountdown'
import { MetaList } from './MetaList'

/*
 * Rows lay themselves out from their own width (container queries), so the same row works in a wide results
 * list, a dashboard column and a phone: columns from 48rem, stacked below.
 */
const COLS = '@3xl:grid-cols-[minmax(0,1fr)_10.5rem_8.5rem_8rem]'
const COLS_WITH_BOOKMARK = '@3xl:grid-cols-[minmax(0,1fr)_10.5rem_8.5rem_8rem_2rem]'

/**
 * One bounty as a dense row: title, summary and facts on the left; funding, deadline and reward in columns.
 * Use inside `BountyList` (or any `divide-y` list). The title is the row's link.
 */
export function BountyRow({
  bounty,
  showBookmark = true,
  showRequester = true,
  className,
}: {
  bounty: BountySummary
  showBookmark?: boolean
  showRequester?: boolean
  className?: string
}) {
  const titleId = `bounty-row-${bounty.id}-title`
  return (
    <article
      aria-labelledby={titleId}
      className={cn(
        'group @container relative transition-colors duration-150 focus-within:bg-muted/40 hover:bg-muted/40',
        className,
      )}
    >
      <div
        className={cn(
          'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 gap-y-2.5 px-4 py-3.5 @3xl:px-5',
          showBookmark ? COLS_WITH_BOOKMARK : COLS,
        )}
      >
        <div className={cn('col-span-2 min-w-0 @3xl:col-span-1', showBookmark && 'pr-9 @3xl:pr-0')}>
          <h3 id={titleId} className="text-sm leading-snug font-semibold">
            <Link
              to={bountyHref(bounty)}
              className="outline-none after:absolute after:inset-0 after:content-[''] focus-visible:underline"
            >
              {bounty.title}
            </Link>
          </h3>
          <p className="mt-0.5 line-clamp-1 text-[0.8125rem] text-muted-foreground">
            {bounty.short_description}
          </p>
          <MetaList className="mt-1.5">
            <span>{CATEGORY_LABELS[bounty.category]}</span>
            <span>{DIFFICULTY_LABELS[bounty.difficulty]}</span>
            <span className="tabular-nums">{applicantsLabel(bounty.applications_count)}</span>
            {!!bounty.questions_count && (
              <span className="tabular-nums">{questionsLabel(bounty.questions_count)}</span>
            )}
            {showRequester && <span className="truncate">{bounty.requester.display_name}</span>}
          </MetaList>
        </div>

        <BountyBadges bounty={bounty} className="@3xl:order-1" />

        <div className="text-right @3xl:order-3">
          <span className="amount text-[0.9375rem]">{formatAmount(bounty.reward_amount)}</span>{' '}
          <span className="text-xs font-medium text-muted-foreground">{bounty.reward_asset.code}</span>
          {bounty.positions_available > 1 && (
            <div className="text-xs text-muted-foreground tabular-nums">
              {bounty.positions_available} positions
            </div>
          )}
        </div>

        <div className="col-span-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs @3xl:order-2 @3xl:col-span-1 @3xl:flex-col @3xl:items-start">
          <DeadlineCountdown deadline={bounty.application_deadline} className="text-xs" />
          <span className="text-muted-foreground tabular-nums">
            {openPositionsOf(bounty)} of {bounty.positions_available} open
          </span>
        </div>

        {showBookmark && (
          <BookmarkButton
            bountyId={bounty.id}
            bookmarked={bounty.is_bookmarked}
            className="absolute top-2.5 right-2 size-8 @3xl:relative @3xl:top-auto @3xl:right-auto @3xl:order-4 @3xl:justify-self-end"
          />
        )}
      </div>
    </article>
  )
}

/** Bounties as a table-style list in one card, with column labels on wide containers. */
export function BountyList({
  bounties,
  showBookmark = true,
  showRequester = true,
  header = true,
  label = 'Bounties',
  className,
}: {
  bounties: BountySummary[]
  showBookmark?: boolean
  showRequester?: boolean
  header?: boolean
  label?: string
  className?: string
}) {
  return (
    <div className={cn('@container overflow-hidden rounded-xl border bg-card shadow-soft', className)}>
      {header && <BountyListHeader showBookmark={showBookmark} />}
      <ul className="divide-y" aria-label={label}>
        {bounties.map((b) => (
          <li key={b.id}>
            <BountyRow bounty={b} showBookmark={showBookmark} showRequester={showRequester} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function BountyListHeader({ showBookmark }: { showBookmark: boolean }) {
  return (
    <div
      aria-hidden
      className={cn(
        'hidden h-9 items-center gap-x-6 border-b bg-surface px-5 text-xs font-medium text-muted-foreground @3xl:grid',
        showBookmark ? COLS_WITH_BOOKMARK : COLS,
      )}
    >
      <span>Bounty</span>
      <span>Status</span>
      <span>Deadline</span>
      <span className="text-right">Reward</span>
      {showBookmark && <span />}
    </div>
  )
}

export function BountyListSkeleton({ count = 6, className }: { count?: number; className?: string }) {
  return (
    <div role="status" aria-live="polite" aria-label="Loading bounties">
      <div
        className={cn('@container overflow-hidden rounded-xl border bg-card shadow-soft', className)}
        aria-hidden
      >
        <div className={cn('hidden h-9 items-center border-b bg-surface @3xl:grid', COLS)} />
        <div className="divide-y">
          {Array.from({ length: count }, (_, i) => (
            <div
              key={i}
              className={cn(
                'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 gap-y-2.5 px-4 py-3.5 @3xl:px-5',
                COLS,
              )}
            >
              <div className="col-span-2 space-y-1.5 @3xl:col-span-1">
                <Skeleton className="h-4 w-3/5" />
                <Skeleton className="h-3.5 w-4/5" />
                <Skeleton className="h-3 w-40" />
              </div>
              <Skeleton className="h-5.5 w-28" />
              <Skeleton className="ml-auto h-5 w-20 @3xl:order-3" />
              <Skeleton className="col-span-2 h-3.5 w-32 @3xl:order-2 @3xl:col-span-1" />
            </div>
          ))}
        </div>
      </div>
      <span className="sr-only">Loading bounties…</span>
    </div>
  )
}
