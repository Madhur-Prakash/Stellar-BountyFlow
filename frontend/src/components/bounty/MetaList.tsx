import { Children, Fragment, type ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** A row of short facts separated by hairlines ("Development | Advanced | 3 applicants"). */
export function MetaList({ children, className }: { children: ReactNode; className?: string }) {
  const items = Children.toArray(children).filter(Boolean)
  return (
    <div
      className={cn('flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted-foreground', className)}
    >
      {items.map((item, i) => (
        <Fragment key={i}>
          {i > 0 && <span aria-hidden className="h-3 w-px shrink-0 bg-border" />}
          {item}
        </Fragment>
      ))}
    </div>
  )
}
