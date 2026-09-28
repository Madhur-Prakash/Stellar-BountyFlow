import { NavLink } from 'react-router'

import { StatGrid, StatTile } from '@/components/common/StatTile'
import type { BountyDetail } from '@/lib/api/types'
import { formatNumber } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

/** Section tabs shared by the requester's views of one bounty (overview, applications, submissions). */
export function ManageBountyNav({
  bountyId,
  applicants,
  className,
}: {
  bountyId: string
  /** Applicant count shown beside "Applications", when known. */
  applicants?: number
  className?: string
}) {
  const base = `/app/bounties/${bountyId}`
  const items = [
    { to: base, label: 'Overview', end: true },
    { to: `${base}/applications`, label: 'Applications', count: applicants },
    { to: `${base}/submissions`, label: 'Submissions' },
  ]
  return (
    <nav aria-label="Bounty sections" className={cn('border-b', className)}>
      <ul className="-mb-px flex gap-5 overflow-x-auto">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'inline-flex h-10 items-center gap-1.5 border-b-2 text-sm font-medium whitespace-nowrap transition-colors',
                  isActive
                    ? 'border-primary text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground',
                )
              }
            >
              {item.label}
              {item.count !== undefined && (
                <span className="rounded-[4px] bg-muted px-1.5 text-xs text-muted-foreground tabular-nums">
                  {item.count}
                </span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function Xlm({ amount, asset }: { amount: string; asset: string }) {
  return (
    <>
      {formatAmount(amount)} <span className="text-sm font-normal text-muted-foreground">{asset}</span>
    </>
  )
}

/** The bounty's reward and positions as one strip (also used on the applications and submissions views). */
export function ManageStats({ bounty, className }: { bounty: BountyDetail; className?: string }) {
  const asset = bounty.reward_asset.code
  return (
    <StatGrid className={cn('grid-cols-2 lg:grid-cols-4', className)}>
      <StatTile label="Applicants" value={formatNumber(bounty.applications_count)} />
      <StatTile
        label="Positions filled"
        value={`${bounty.positions_filled} / ${bounty.positions_available}`}
      />
      <StatTile label="Reward per position" value={<Xlm amount={bounty.reward_amount} asset={asset} />} />
      <StatTile label="Total reward" value={<Xlm amount={bounty.total_reward} asset={asset} />} />
    </StatGrid>
  )
}
