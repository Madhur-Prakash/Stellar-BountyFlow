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
