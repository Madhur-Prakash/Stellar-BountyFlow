import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export function PageContainer({
  children,
  className,
  size = 'default',
}: {
  children: ReactNode
  className?: string
  size?: 'narrow' | 'default' | 'wide'
}) {
  return (
    <div
      className={cn(
        'mx-auto w-full px-4 sm:px-6 lg:px-8 2xl:px-12',
        size === 'narrow' && 'max-w-3xl',
        size === 'default' && 'max-w-384',
        size === 'wide' && 'max-w-448',
        className,
      )}
    >
      {children}
    </div>
  )
}
