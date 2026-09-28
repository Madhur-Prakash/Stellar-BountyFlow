import type { ReactNode } from 'react'

import { SplitHeading } from '@/components/motion/SplitHeading'
import { cn } from '@/lib/utils'

export function SectionHeading({
  id,
  title,
  description,
  className,
  tone = 'default',
}: {
  id: string
  title: string
  description?: ReactNode
  className?: string
  /** `vault`: light text for the dark escrow band. */
  tone?: 'default' | 'vault'
}) {
  return (
    <div className={cn('max-w-2xl', className)}>
      <SplitHeading
        id={id}
        className="font-display text-[2.25rem] leading-[1.02] sm:text-[3rem] lg:text-[3.5rem]"
      >
        {title}
      </SplitHeading>
      {description && (
        <p
          className={cn(
            'mt-4 text-[1.0625rem] leading-relaxed',
            tone === 'vault' ? 'text-vault-muted' : 'text-muted-foreground',
          )}
        >
          {description}
        </p>
      )}
    </div>
  )
}
