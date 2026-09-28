import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * "Nothing here yet" for a list or section: an icon tile, a title, a short description and an optional action.
 * On the canvas it gets a dashed outline; inside a Card it sits flush with the card.
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
        'flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-10 text-center',
        'in-data-[slot=card]:rounded-none in-data-[slot=card]:border-0 in-data-[slot=card]:py-8',
        className,
      )}
    >
      {Icon && (
        <div className="mb-3 flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="size-5" aria-hidden />
        </div>
      )}
      <h3 className="text-[0.9375rem] font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  )
}
