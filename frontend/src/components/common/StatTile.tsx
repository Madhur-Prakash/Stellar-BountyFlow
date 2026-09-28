import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/**
 * One figure: a quiet label above a tabular number (Geist 500, tight), with an optional hint. Tiles are usually
 * laid out in a `StatGrid`, which draws them as one bordered strip. The `icon` prop is accepted for call-site
 * compatibility but not drawn.
 */
export function StatTile({
  label,
  value,
  hint,
  loading,
  className,
}: {
  label: string
  value: ReactNode
  icon?: LucideIcon
  hint?: ReactNode
  loading?: boolean
  className?: string
}) {
  return (
    <div data-stat-tile className={cn('min-w-0 bg-card px-5 py-4', className)}>
      <div className="text-[0.8125rem] leading-snug text-muted-foreground">{label}</div>
      <div className="mt-2 text-[1.75rem] leading-none font-medium tracking-[-0.035em] tabular-nums">
        {loading ? <Skeleton className="h-7 w-20" /> : value}
      </div>
      {hint && <div className="mt-2 text-xs leading-snug text-muted-foreground">{hint}</div>}
    </div>
  )
}

/**
 * Stat tiles as one card: a hairline grid (1px gaps over the border colour) so rows and columns share dividers
 * at every breakpoint. Pass the column classes, e.g. `grid-cols-2 lg:grid-cols-4`.
 */
export function StatGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('grid gap-px overflow-hidden rounded-xl border bg-border shadow-soft', className)}>
      {children}
    </div>
  )
}
