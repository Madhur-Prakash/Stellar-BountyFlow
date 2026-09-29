import { Link } from 'react-router'

import { UserAvatar } from '@/components/common/UserAvatar'
import type { BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

import { BookmarkButton } from './BookmarkButton'
import { applicantsLabel, bountyHref, openPositionsOf, questionsLabel } from './bounty-display'
import { BountyStatusBadge } from './BountyStatusBadge'
import { DeadlineCountdown } from './DeadlineCountdown'
import { FundingStatusBadge } from './FundingStatusBadge'
import { MetaList } from './MetaList'
import { RewardDisplay } from './RewardDisplay'
import { SkillTags } from './SkillTags'

/** Funding first, then status (skipped when "Funded in escrow" already says it). */
export function BountyBadges({ bounty, className }: { bounty: BountySummary; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
      {bounty.status !== 'FUNDED' && <BountyStatusBadge status={bounty.status} />}
    </div>
  )
}

/** A bounty in a grid of results. The whole card is one link (the title); the bookmark sits above it. */
export function BountyCard({
  bounty,
  showBookmark = true,
  showRequester = true,
  className,
}: {
  bounty: BountySummary
  showBookmark?: boolean
  /** Off where every card has the same requester (a profile). */
  showRequester?: boolean
  className?: string
}) {
  const openPositions = openPositionsOf(bounty)

  return (
    <article
      className={cn(
        'group relative flex h-full flex-col rounded-xl border bg-card p-5 shadow-soft transition-colors duration-150 focus-within:border-ring/60 hover:border-foreground/20',
        className,
      )}
      aria-labelledby={`bounty-${bounty.id}-title`}
    >
      <div className="flex min-h-7 items-start justify-between gap-2">
        <BountyBadges bounty={bounty} />
        {showBookmark && (
          <BookmarkButton
            bountyId={bounty.id}
            bookmarked={bounty.is_bookmarked}
            className="-mt-1.5 -mr-2.5 size-8"
          />
        )}
      </div>

      <h3 id={`bounty-${bounty.id}-title`} className="mt-2.5 text-[0.9375rem] leading-snug font-semibold">
        <Link
          to={bountyHref(bounty)}
          className="outline-none after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:underline"
        >
          {bounty.title}
        </Link>
      </h3>
      <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{bounty.short_description}</p>

      <MetaList className="mt-3">
        <span>{CATEGORY_LABELS[bounty.category]}</span>
        <span>{DIFFICULTY_LABELS[bounty.difficulty]}</span>
        <span className="tabular-nums">{applicantsLabel(bounty.applications_count)}</span>
        {!!bounty.questions_count && (
          <span className="tabular-nums">{questionsLabel(bounty.questions_count)}</span>
        )}
      </MetaList>

      <SkillTags skills={bounty.required_skills} max={3} className="mt-3" label="Required skills" />

      <div className="min-h-4 flex-1" aria-hidden />
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-x-3 border-t pt-4">
        <RewardDisplay
          rewardAmount={bounty.reward_amount}
          totalReward={bounty.total_reward}
          positions={bounty.positions_available}
          assetCode={bounty.reward_asset.code}
          size="sm"
        />
        <div className="flex flex-col items-end gap-1 text-right text-xs">
          <DeadlineCountdown deadline={bounty.application_deadline} className="text-xs" />
          <span className="text-muted-foreground tabular-nums">
            {openPositions} of {bounty.positions_available} open
          </span>
        </div>
      </div>

      {showRequester && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <UserAvatar user={bounty.requester} className="size-5" />
          <span className="truncate">{bounty.requester.display_name}</span>
        </div>
      )}
    </article>
  )
}
