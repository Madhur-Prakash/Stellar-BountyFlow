import { Check, CircleAlert } from 'lucide-react'

import type { BountyDetail, BountyStatus } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

const MAIN: { status: BountyStatus; label: string }[] = [
  { status: 'OPEN', label: 'Published' },
  { status: 'FUNDED', label: 'Funded' },
  { status: 'IN_PROGRESS', label: 'In progress' },
  { status: 'UNDER_REVIEW', label: 'Under review' },
  { status: 'COMPLETED', label: 'Completed' },
]

/** Position of each status along the happy path. */
const ORDER: Partial<Record<BountyStatus, number>> = {
  DRAFT: -1,
  OPEN: 0,
  FUNDING_PENDING: 0,
  FUNDED: 1,
  IN_PROGRESS: 2,
  UNDER_REVIEW: 3,
  COMPLETED: 4,
}

const EXCEPTIONAL: BountyStatus[] = ['CANCEL_REQUESTED', 'CANCELLED', 'DISPUTED', 'EXPIRED']

export function BountyTimeline({
  bounty,
  className,
}: {
  bounty: Pick<BountyDetail, 'status' | 'funding_status'>
  className?: string
}) {
  const exceptional = EXCEPTIONAL.includes(bounty.status)
  // For exceptional states we can only be sure about "published"; funding is shown from funding_status.
  const reached = exceptional
    ? bounty.funding_status === 'FUNDED' ||
      bounty.funding_status === 'SETTLED' ||
      bounty.funding_status === 'REFUNDED' ||
      bounty.funding_status === 'REFUND_PENDING'
      ? 1
      : 0
    : (ORDER[bounty.status] ?? 0)

  return (
    <div className={className}>
      <ol className="grid grid-cols-5 gap-1.5" aria-label="Bounty lifecycle">
        {MAIN.map((step, i) => {
          const done = i < reached || (i === reached && bounty.status === 'COMPLETED')
          const current = !exceptional && i === reached && bounty.status !== 'COMPLETED'
          return (
            <li key={step.status} className="min-w-0" aria-current={current ? 'step' : undefined}>
              <div
                className={cn(
                  'h-1 rounded-full',
                  done ? 'bg-primary' : current ? 'bg-primary/45' : 'bg-border',
                )}
              />
              <div
                className={cn(
                  // Labels wrap on narrow screens instead of truncating to "In progre…".
                  'mt-2 flex items-start gap-1 text-[0.6875rem] leading-tight sm:text-xs',
                  done || current ? 'text-foreground' : 'text-muted-foreground',
                  current && 'font-medium',
                )}
              >
                {done && (
                  <Check className="mt-px size-3 shrink-0 text-primary max-[400px]:hidden" aria-hidden />
                )}
                <span className="min-w-0 wrap-break-word">{step.label}</span>
                <span className="sr-only">{done ? ' (done)' : current ? ' (current)' : ''}</span>
              </div>
            </li>
          )
        })}
      </ol>
      {bounty.status === 'FUNDING_PENDING' && (
        <p className="mt-3 text-xs text-muted-foreground">Waiting for the network to confirm funding.</p>
      )}
      {exceptional && (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-warning">
          <CircleAlert className="size-4" aria-hidden /> {BOUNTY_STATUS_LABELS[bounty.status]}
        </p>
      )}
    </div>
  )
}
