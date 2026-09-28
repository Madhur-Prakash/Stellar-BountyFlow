import { CheckCircle2, CircleAlert, Clock3, LoaderCircle, PenLine, TimerOff } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { TxStatus } from '@/lib/api/types'
import { TX_STATUS_LABELS } from '@/lib/format'

const MAP: Record<
  TxStatus,
  { variant: 'success' | 'warning' | 'danger' | 'info' | 'muted'; icon: typeof Clock3 }
> = {
  CREATED: { variant: 'muted', icon: Clock3 },
  SIGNATURE_REQUIRED: { variant: 'warning', icon: PenLine },
  SUBMITTED: { variant: 'info', icon: LoaderCircle },
  CONFIRMED: { variant: 'success', icon: CheckCircle2 },
  FAILED: { variant: 'danger', icon: CircleAlert },
  EXPIRED: { variant: 'muted', icon: TimerOff },
}

export function TxStatusBadge({ status }: { status: TxStatus }) {
  const { variant, icon: Icon } = MAP[status]
  return (
    <Badge variant={variant}>
      <Icon className={status === 'SUBMITTED' ? 'animate-spin' : undefined} aria-hidden />
      {TX_STATUS_LABELS[status]}
    </Badge>
  )
}
