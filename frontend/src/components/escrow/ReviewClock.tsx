import { Clock3 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { useCountdown } from '@/hooks/useCountdown'
import type { OnchainReview } from '@/lib/api/types'
import { formatDateTime } from '@/lib/format'
import { ONCHAIN_REVIEW_LABELS } from '@/lib/escrow'
import { cn } from '@/lib/utils'

function remaining(ms: number): string {
  const total = Math.floor(ms / 1000)
  const d = Math.floor(total / 86_400)
  const h = Math.floor((total % 86_400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  if (d > 0) return `${d}d ${pad(h)}h`
  if (h > 0) return `${h}h ${pad(m)}m`
  return `${m}m ${pad(s)}s`
}

/**
 * The on-chain review clock of one submission, from the requester's or the contributor's side. The countdown
 * ticks locally; whether a claim or an answer is still possible is decided by the contract.
 */
export function ReviewClock({
  review,
  perspective,
  compact = false,
  className,
}: {
  review: OnchainReview
  perspective: 'requester' | 'contributor'
  /** One line for tables: "Claim in 6d 23h" / "Claim open". */
  compact?: boolean
  className?: string
}) {
  const c = useCountdown(review.state === 'PENDING' ? review.claimable_at : null)
  if (review.state === 'PAID') return null
  if (compact && review.state === 'PENDING') {
    const open = !c || c.isPast
    return (
      <span className={cn('inline-flex items-center gap-1.5 text-sm tabular-nums', className)}>
        <Clock3 className={cn('size-3.5', open ? 'text-warning' : 'text-muted-foreground')} aria-hidden />
        {open
          ? perspective === 'contributor'
            ? 'Claim open'
            : 'Window passed'
          : `${perspective === 'contributor' ? 'Claim in' : 'Answer within'} ${remaining(c.remainingMs)}`}
      </span>
    )
  }
  if (review.state !== 'PENDING') {
    return (
      <Badge variant={review.state === 'REJECTED' ? 'danger' : 'warning'} className={className}>
        {ONCHAIN_REVIEW_LABELS[review.state]}
      </Badge>
    )
  }
  const due = review.claimable_at
  const passed = !c || c.isPast
  const text = passed
    ? perspective === 'contributor'
      ? 'Review window passed. You can claim the payment.'
      : 'Review window passed. The contributor can claim the payment; you can still pay it.'
    : perspective === 'contributor'
      ? `Claim opens in ${remaining(c.remainingMs)} if the requester does not answer.`
      : `Answer within ${remaining(c.remainingMs)}, or the contributor can claim the payment.`
  return (
    <p
      className={cn(
        'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm',
        passed ? 'border-warning/30 bg-warning/8' : 'bg-surface/60',
        className,
      )}
    >
      <Clock3
        className={cn('mt-0.5 size-4 shrink-0', passed ? 'text-warning' : 'text-muted-foreground')}
        aria-hidden
      />
      <span>
        <span className="font-medium">Recorded on-chain. </span>
        {text}
        {due && (
          <>
            {' '}
            <time dateTime={due} className="text-muted-foreground tabular-nums">
              ({formatDateTime(due)})
            </time>
          </>
        )}
      </span>
    </p>
  )
}
