import { ExternalLink } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { Milestone } from '@/lib/api/types'
import { formatDate } from '@/lib/format'
import { MILESTONE_STATUS_LABELS } from '@/lib/escrow'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

/**
 * The milestones of a single-position bounty in order, with what has been paid. "Paid" only appears once the
 * payout was verified on-chain.
 */
export function MilestoneTimeline({
  milestones,
  assetCode,
  className,
}: {
  milestones: Milestone[]
  assetCode: string
  className?: string
}) {
  return (
    <ol className={cn('relative space-y-0', className)} aria-label="Milestones">
      {milestones.map((m, i) => {
        const paid = m.status === 'PAID'
        const last = i === milestones.length - 1
        return (
          <li key={m.id} className="relative flex gap-3 pb-4 last:pb-0">
            {!last && (
              <span
                aria-hidden
                className={cn(
                  'absolute top-6 bottom-0 left-[0.6875rem] w-px',
                  paid ? 'bg-success/50' : 'bg-border',
                )}
              />
            )}
            <span
              aria-hidden
              className={cn(
                'relative mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium tabular-nums',
                paid ? 'border-success/40 bg-success/10 text-success' : 'bg-card text-muted-foreground',
              )}
            >
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="font-medium">{m.title}</span>
                <span className="amount text-sm">
                  {formatAmount(m.amount)} {assetCode}
                </span>
              </div>
              {m.description && <p className="mt-0.5 text-sm text-muted-foreground">{m.description}</p>}
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant={paid ? 'success' : m.status === 'SETTLED' ? 'info' : 'muted'}>
                  {MILESTONE_STATUS_LABELS[m.status]}
                </Badge>
                {m.paid_at && <span>{formatDate(m.paid_at)}</span>}
                {m.explorer_url && (
                  <a
                    href={m.explorer_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Payout transaction <ExternalLink className="size-3" aria-hidden />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
