import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** A section title with an optional description on the left and optional actions on the right. */
export function SectionHeading({
  id,
  title,
  description,
  actions,
  className,
}: {
  id: string
  title: string
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="max-w-2xl">
        <h2 id={id} className="font-display text-[1.625rem] leading-tight sm:text-[1.875rem]">
          {title}
        </h2>
        {description && (
          <p className="mt-2 text-[0.9375rem] leading-relaxed text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Vertical rhythm shared by every landing section. */
export const SECTION = 'py-12 sm:py-16'
