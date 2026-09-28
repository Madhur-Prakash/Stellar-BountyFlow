import {
  ArrowDownLeft,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  CircleOff,
  CircleSlash,
  Clock3,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { BountyStatus, FundingStatus } from '@/lib/api/types'
import { FUNDING_STATUS_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

type Variant = 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'outline'

type Display = { label: string; variant: Variant; icon: LucideIcon; tone: string }

const FUNDING: Record<FundingStatus, Display> = {
  FUNDED: { label: FUNDING_STATUS_LABELS.FUNDED, variant: 'success', icon: ShieldCheck, tone: 'funded' },
  PARTIALLY_FUNDED: {
    label: FUNDING_STATUS_LABELS.PARTIALLY_FUNDED,
    variant: 'warning',
    icon: CircleDashed,
    tone: 'partial',
  },
  PENDING: { label: FUNDING_STATUS_LABELS.PENDING, variant: 'info', icon: Clock3, tone: 'pending' },
  UNFUNDED: { label: FUNDING_STATUS_LABELS.UNFUNDED, variant: 'outline', icon: CircleOff, tone: 'unfunded' },
  REFUND_PENDING: {
    label: FUNDING_STATUS_LABELS.REFUND_PENDING,
    variant: 'warning',
    icon: ArrowDownLeft,
    tone: 'refund-pending',
  },
  REFUNDED: {
    label: FUNDING_STATUS_LABELS.REFUNDED,
    variant: 'muted',
    icon: ArrowDownLeft,
    tone: 'refunded',
  },
  SETTLED: { label: 'Paid out', variant: 'success', icon: CheckCircle2, tone: 'settled' },
}

/**
 * Funding state is shown independently of bounty status so a visitor can
 * always tell whether rewards are actually locked in escrow. The word
 * "Funded" is only ever used when `funding_status === "FUNDED"`.
 */
function fundingDisplay(status: FundingStatus, bountyStatus?: BountyStatus): Display {
  if (bountyStatus === 'DISPUTED' && (status === 'FUNDED' || status === 'PARTIALLY_FUNDED')) {
    return { label: 'Disputed, escrow locked', variant: 'danger', icon: CircleAlert, tone: 'disputed' }
  }
  if (bountyStatus === 'CANCELLED' && (status === 'UNFUNDED' || status === 'PENDING')) {
    return { label: 'Cancelled before funding', variant: 'muted', icon: CircleSlash, tone: 'cancelled' }
  }
  if (bountyStatus === 'COMPLETED' && status === 'SETTLED') {
    // The status badge already says "Completed"; the funding badge only adds where the money went.
    return { label: 'Paid out', variant: 'success', icon: CheckCircle2, tone: 'completed' }
  }
  return FUNDING[status]
}

export function FundingStatusBadge({
  status,
  bountyStatus,
  className,
}: {
  status: FundingStatus
  bountyStatus?: BountyStatus
  className?: string
}) {
  const d = fundingDisplay(status, bountyStatus)
  const Icon = d.icon
  return (
    <Badge
      variant={d.variant}
      data-funding={d.tone}
      className={cn(d.variant === 'outline' && 'text-muted-foreground', className)}
    >
      <Icon aria-hidden />
      <span>
        <span className="sr-only">Funding: </span>
        {d.label}
      </span>
    </Badge>
  )
}
