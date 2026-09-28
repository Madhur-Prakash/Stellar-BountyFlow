import { Clock3 } from 'lucide-react'

import { useCountdown } from '@/hooks/useCountdown'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * "Closes in 3d 04h". Updates live, but is not announced every second.
 * `bare` drops the icon and the label ("in 3d 04h"), for use next to its own label.
 */
export function DeadlineCountdown({
  deadline,
  label = 'Closes',
  className,
  showSeconds = false,
  bare = false,
}: {
  deadline: string | null | undefined
  label?: string
  className?: string
  showSeconds?: boolean
  bare?: boolean
}) {
  const c = useCountdown(deadline)
  if (!deadline || !c) {
    return (
      <span className={cn('inline-flex items-center gap-1.5 text-sm text-muted-foreground', className)}>
        {!bare && <Clock3 className="size-3.5" aria-hidden />} No deadline
      </span>
    )
  }
  const urgent = !c.isPast && c.remainingMs < 48 * 3600_000
  const pad = (n: number) => String(n).padStart(2, '0')
  const text = c.isPast
    ? 'Closed'
    : c.days > 0
      ? `${c.days}d ${pad(c.hours)}h`
      : showSeconds
        ? `${pad(c.hours)}h ${pad(c.minutes)}m ${pad(c.seconds)}s`
        : `${pad(c.hours)}h ${pad(c.minutes)}m`
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-sm tabular-nums',
        c.isPast ? 'text-muted-foreground' : urgent ? 'text-warning' : 'text-foreground',
        className,
      )}
    >
      {!bare && <Clock3 className="size-3.5" aria-hidden />}
      <time dateTime={deadline} title={formatDateTime(deadline)}>
        {c.isPast ? text : bare ? `in ${text}` : `${label} in ${text}`}
      </time>
    </span>
  )
}
