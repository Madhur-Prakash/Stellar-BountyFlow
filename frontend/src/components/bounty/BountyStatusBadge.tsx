import {
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  CircleDot,
  CircleSlash,
  Clock3,
  FileCheck2,
  Hammer,
  PencilLine,
  ShieldCheck,
  TimerOff,
  type LucideIcon,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { BountyStatus } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

type Variant = 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'cyan'

const MAP: Record<BountyStatus, { variant: Variant; icon: LucideIcon }> = {
  DRAFT: { variant: 'muted', icon: PencilLine },
  OPEN: { variant: 'info', icon: CircleDot },
  FUNDING_PENDING: { variant: 'warning', icon: Clock3 },
  FUNDED: { variant: 'success', icon: ShieldCheck },
  IN_PROGRESS: { variant: 'cyan', icon: Hammer },
  UNDER_REVIEW: { variant: 'cyan', icon: FileCheck2 },
  COMPLETED: { variant: 'success', icon: CheckCircle2 },
  CANCEL_REQUESTED: { variant: 'warning', icon: CircleDashed },
  CANCELLED: { variant: 'muted', icon: CircleSlash },
  DISPUTED: { variant: 'danger', icon: CircleAlert },
  EXPIRED: { variant: 'muted', icon: TimerOff },
}

const DOT: Record<Variant, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-destructive',
  info: 'bg-primary',
  muted: 'bg-muted-foreground/70',
  cyan: 'bg-cyan',
}

/** The status colour as a small dot, for group and column headers (never as a chip). */
export function BountyStatusDot({ status, className }: { status: BountyStatus; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('inline-block size-2 shrink-0 rounded-full', DOT[MAP[status].variant], className)}
    />
  )
}

export function BountyStatusBadge({ status, className }: { status: BountyStatus; className?: string }) {
  const { variant, icon: Icon } = MAP[status]
  return (
    <Badge variant={variant} className={className}>
      <Icon aria-hidden />
      <span>
        <span className="sr-only">Status: </span>
        {BOUNTY_STATUS_LABELS[status]}
      </span>
    </Badge>
  )
}
