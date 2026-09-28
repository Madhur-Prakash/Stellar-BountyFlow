import type { ReactNode } from 'react'

import { MonoLabel } from '@/components/marketing/MonoLabel'
import { cn } from '@/lib/utils'

/** The marketing H2: Geist, large and light, tight tracking. */
export const SECTION_TITLE = 'font-display text-[2rem] leading-[1.08] sm:text-[2.5rem] lg:text-[2.75rem]'

/** The paragraph under a marketing heading: larger, warm grey. */
export const SECTION_LEAD = 'text-[1.0625rem] leading-relaxed text-muted-foreground sm:text-lg'

/**
 * A section title with an optional mono label above it, a description under it, and optional actions on the
 * right.
 */
export function SectionHeading({
  id,
  title,
  label,
  description,
  actions,
  align = 'start',
  className,
}: {
  id: string
  title: string
  label?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  align?: 'start' | 'center'
  className?: string
}) {
  const centered = align === 'center'
  return (
    <div
      className={cn(
        'flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between',
        centered && 'items-center text-center sm:flex-col sm:items-center',
        className,
      )}
    >
      <div className={cn('max-w-2xl', centered && 'mx-auto')}>
        {label && <MonoLabel className="mb-3">{label}</MonoLabel>}
        <h2 id={id} className={SECTION_TITLE}>
          {title}
        </h2>
        {description && <p className={cn('mt-4', SECTION_LEAD)}>{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Vertical rhythm shared by every landing section. */
export const SECTION = 'py-16 sm:py-24'
