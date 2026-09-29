import { CircleAlert, CircleCheck, CircleDashed, CircleHelp, CircleOff, type LucideIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { TrustlineState } from '@/lib/api/types'
import { cn } from '@/lib/utils'

type Display = {
  label: (code: string) => string
  variant: 'info' | 'warning' | 'muted' | 'outline'
  icon: LucideIcon
}

// Green is reserved for money in escrow or paid, so a working trustline uses the blue tint.
const DISPLAY: Record<TrustlineState, Display> = {
  ACTIVE: { label: (c) => `${c} trustline`, variant: 'info', icon: CircleCheck },
  NOT_REQUIRED: { label: (c) => `Receives ${c}`, variant: 'outline', icon: CircleCheck },
  MISSING: { label: (c) => `No ${c} trustline`, variant: 'warning', icon: CircleAlert },
  UNAUTHORIZED: { label: (c) => `${c} not authorized`, variant: 'warning', icon: CircleAlert },
  ACCOUNT_MISSING: { label: () => 'Account not funded', variant: 'warning', icon: CircleOff },
  NO_WALLET: { label: () => 'No verified wallet', variant: 'muted', icon: CircleDashed },
  UNKNOWN: { label: () => 'Not checked', variant: 'muted', icon: CircleHelp },
}

/** Whether a wallet can receive an asset, as a square tinted tag. */
export function TrustlineBadge({
  state,
  code,
  className,
}: {
  state: TrustlineState
  code: string
  className?: string
}) {
  const d = DISPLAY[state]
  const Icon = d.icon
  return (
    <Badge variant={d.variant} data-trustline={state} className={cn(className)}>
      <Icon aria-hidden />
      {d.label(code)}
    </Badge>
  )
}
