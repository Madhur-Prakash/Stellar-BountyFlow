import { ExternalLink } from 'lucide-react'

import { truncateMiddle } from '@/lib/stellar/explorer'
import { cn } from '@/lib/utils'

import { CopyButton } from './CopyButton'

/**
 * Monospace, truncated value (address / hash / contract id) with the full
 * value in a title + copy button, and an optional explorer link.
 */
export function MonoValue({
  value,
  label,
  href,
  lead = 6,
  tail = 6,
  className,
  copy = true,
}: {
  value: string | null | undefined
  /** What the value is, used in accessible labels ("transaction hash"). */
  label: string
  href?: string | null
  lead?: number
  tail?: number
  className?: string
  copy?: boolean
}) {
  if (!value) return <span className="text-muted-foreground">—</span>
  return (
    <span className={cn('inline-flex max-w-full items-center gap-0.5', className)}>
      <code
        className="truncate rounded-md bg-muted/60 px-1.5 py-0.5 font-mono text-[0.8125rem] text-foreground"
        title={value}
      >
        <span className="sr-only">{label}: </span>
        {truncateMiddle(value, lead, tail)}
      </code>
      {copy && <CopyButton value={value} label={`Copy ${label}`} />}
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground"
          aria-label={`View ${label} on Stellar explorer (opens in a new tab)`}
        >
          <ExternalLink className="size-4" />
        </a>
      )}
    </span>
  )
}
