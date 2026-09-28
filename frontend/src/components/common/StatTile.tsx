import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/** A single figure: the number set in condensed Plex, its label underneath. The `icon` prop is accepted for
 * call-site compatibility but not drawn; decorative corner icons added noise without information. */
export function StatTile({
  label,
  value,
  hint,
  loading,
  className,
}: {
  label: string
  value: ReactNode
  icon?: LucideIcon
  hint?: ReactNode
  loading?: boolean
  className?: string
}) {
  return (
    <div className={cn('rounded-lg border bg-card px-4 py-3.5', className)}>
      <div className="amount text-[2rem] leading-none">
        {loading ? <Skeleton className="h-8 w-20" /> : value}
      </div>
      <div className="mt-2 text-sm text-muted-foreground">{label}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}
