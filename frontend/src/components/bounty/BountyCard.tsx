import { Users } from 'lucide-react'
import { Link } from 'react-router'

import { UserAvatar } from '@/components/common/UserAvatar'
import type { BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

import { BookmarkButton } from './BookmarkButton'
import { BountyStatusBadge } from './BountyStatusBadge'
import { DeadlineCountdown } from './DeadlineCountdown'
import { FundingStatusBadge } from './FundingStatusBadge'
import { RewardDisplay } from './RewardDisplay'
import { SkillTags } from './SkillTags'

export function BountyCard({
  bounty,
  showBookmark = true,
  className,
}: {
  bounty: BountySummary
  showBookmark?: boolean
  className?: string
}) {
  const openPositions = Math.max(0, bounty.positions_available - bounty.positions_filled)
  const href = `/bounties/${bounty.slug || bounty.id}`

  return (
    <article
      className={cn(
        'group relative flex h-full flex-col rounded-xl border bg-card p-5 shadow-soft transition-[border-color,box-shadow,translate] duration-300 ease-out focus-within:border-ring hover:-translate-y-0.5 hover:border-foreground/15 hover:shadow-lift',
        className,
      )}
      aria-labelledby={`bounty-${bounty.id}-title`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
          {/* "Funded in escrow" already says it; a second "Funded" badge would only repeat it. */}
          {bounty.status !== 'FUNDED' && <BountyStatusBadge status={bounty.status} />}
        </div>
        {showBookmark && (
          <BookmarkButton bountyId={bounty.id} bookmarked={bounty.is_bookmarked} className="-mt-1.5 -mr-2" />
        )}
      </div>

      <h3 id={`bounty-${bounty.id}-title`} className="mt-3 text-base leading-snug font-semibold">
        <Link
          to={href}
          className="outline-none after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:underline"
        >
          {bounty.title}
        </Link>
      </h3>
      <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">{bounty.short_description}</p>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{CATEGORY_LABELS[bounty.category]}</span>
        <span>{DIFFICULTY_LABELS[bounty.difficulty]}</span>
        <span className="inline-flex items-center gap-1 tabular-nums">
          <Users className="size-3.5" aria-hidden /> {bounty.applications_count} applicant
          {bounty.applications_count === 1 ? '' : 's'}
        </span>
      </div>

      <SkillTags skills={bounty.required_skills} max={4} className="mt-3" label="Required skills" />

      <div className="min-h-5 flex-1" aria-hidden />
      <div className="flex flex-wrap items-end justify-between gap-3 border-t pt-4">
        <RewardDisplay
          rewardAmount={bounty.reward_amount}
          totalReward={bounty.total_reward}
          positions={bounty.positions_available}
          assetCode={bounty.reward_asset.code}
          size="sm"
        />
        <div className="flex flex-col items-end gap-1 text-right">
          <DeadlineCountdown deadline={bounty.application_deadline} className="text-xs" />
          <span className="text-xs text-muted-foreground tabular-nums">
            {openPositions} of {bounty.positions_available} open
          </span>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
        <UserAvatar user={bounty.requester} className="size-5" />
        <span className="truncate">by {bounty.requester.display_name}</span>
      </div>
    </article>
  )
}
