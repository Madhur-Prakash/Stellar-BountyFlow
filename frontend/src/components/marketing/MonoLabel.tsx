import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * The small monospace label that sits above a marketing heading ("Escrow", "Lifecycle"): IBM Plex Mono, 13px,
 * muted. Use one word or two, sentence case.
 */
export function MonoLabel({
  children,
  className,
  as: Tag = 'p',
}: {
  children: ReactNode
  className?: string
  as?: 'p' | 'span' | 'div'
}) {
  return <Tag className={cn('label-mono', className)}>{children}</Tag>
}
