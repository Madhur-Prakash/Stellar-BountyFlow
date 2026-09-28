import { CloudOff, FlaskConical, Globe, LoaderCircle, type LucideIcon } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { BlockchainMode } from '@/lib/api/types'
import { cn } from '@/lib/utils'

const STYLES: Record<BlockchainMode, { label: string; icon: LucideIcon; tone: string; hint: string }> = {
  testnet: {
    label: 'Testnet',
    icon: FlaskConical,
    tone: 'text-cyan',
    hint: 'Transactions run on Stellar Testnet. Test XLM has no monetary value.',
  },
  mainnet: {
    label: 'Mainnet',
    icon: Globe,
    tone: 'text-success',
    hint: 'Transactions run on the Stellar public network with real XLM.',
  },
}

const BASE =
  'inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[0.8125rem] font-medium whitespace-nowrap text-muted-foreground [&_svg]:size-3.5 [&_svg]:shrink-0'

/** The network the API is connected to: an icon and a word, never a chip. */
export function NetworkBadge({ className, compact = false }: { className?: string; compact?: boolean }) {
  const { data, isPending, isError } = usePublicConfig()

  if (isPending) {
    return (
      <span className={cn(BASE, 'font-normal', className)} aria-live="polite">
        <LoaderCircle className="animate-spin" aria-hidden />
        Connecting
      </span>
    )
  }

  if (isError || !data) {
    return (
      <span
        className={cn(BASE, 'text-warning', className)}
        title="BountyFlow can’t be reached right now."
        role="status"
      >
        <CloudOff aria-hidden />
        Offline
      </span>
    )
  }

  const s = STYLES[data.blockchain_mode] ?? STYLES.testnet
  const Icon = s.icon
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn(BASE, 'transition-colors hover:bg-muted hover:text-foreground', className)}
          aria-label={`Active network: ${s.label}`}
        >
          <Icon className={s.tone} aria-hidden />
          {compact ? s.label : `Stellar ${s.label}`}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{s.hint}</TooltipContent>
    </Tooltip>
  )
}
