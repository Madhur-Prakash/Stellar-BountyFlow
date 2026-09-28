import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** The three window controls in the title bar. Decorative. */
function WindowDots() {
  return (
    <span aria-hidden className="flex shrink-0 items-center gap-1.5">
      <span className="size-2.75 rounded-full bg-[#ff5f57]" />
      <span className="size-2.75 rounded-full bg-[#febc2e]" />
      <span className="size-2.75 rounded-full bg-[#28c840]" />
    </span>
  )
}

/**
 * A framed product panel: a window with a title bar (three dots, an optional title and toolbar) around real
 * product UI. Marketing pages set it on an `Atmosphere` backdrop. The title is plain text, not a heading, so it
 * never competes with the section's own heading.
 */
export function AppWindow({
  title,
  toolbar,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode
  toolbar?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <div
      className={cn(
        'overflow-hidden rounded-xl border bg-card text-card-foreground',
        'shadow-[0_1px_2px_rgb(27_26_23/0.06),0_24px_60px_-24px_rgb(27_26_23/0.28)]',
        'dark:border-white/10 dark:shadow-[0_0_0_1px_rgb(0_0_0/0.4),0_32px_80px_-24px_rgb(0_0_0/0.75)]',
        className,
      )}
    >
      <div className="flex h-10 items-center gap-3 border-b px-3.5 sm:px-4">
        <WindowDots />
        {title && (
          <div className="flex min-w-0 items-center gap-2 truncate text-[0.8125rem] font-medium">{title}</div>
        )}
        {toolbar && <div className="ml-auto flex shrink-0 items-center gap-2">{toolbar}</div>}
      </div>
      <div className={bodyClassName}>{children}</div>
    </div>
  )
}
