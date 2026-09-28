import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * "Nothing here yet" for a list or section: a hairline icon tile, a title, a short description and an optional
 * action. On the canvas it gets a dashed outline; inside a Card it sits flush with the card.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-dashed bg-card/40 px-6 py-12 text-center',
        'in-data-[slot=card]:rounded-none in-data-[slot=card]:border-0 in-data-[slot=card]:bg-transparent in-data-[slot=card]:py-10',
        className,
      )}
    >
      {Icon && (
        <div className="mb-4 flex size-9 items-center justify-center rounded-lg border bg-surface text-muted-foreground shadow-soft">
          <Icon className="size-4" aria-hidden />
        </div>
      )}
      <h3 className="text-[0.9375rem] leading-snug font-medium tracking-[-0.01em]">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  )
}
