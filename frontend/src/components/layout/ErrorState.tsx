import { CircleAlert, RotateCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { errorMessage, isApiError } from '@/lib/api/client'
import { cn } from '@/lib/utils'

/** A section that failed to load: the same layout as EmptyState, tinted, with a retry. */
export function ErrorState({
  error,
  title = 'Could not load this',
  onRetry,
  className,
}: {
  error?: unknown
  title?: string
  onRetry?: () => void
  className?: string
}) {
  const requestId = isApiError(error) ? error.requestId : null
  return (
    <div
      role="alert"
      aria-live="assertive"
      data-slot="error-state"
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-destructive/25 bg-destructive/4 px-6 py-12 text-center',
        'in-data-[slot=card]:rounded-none in-data-[slot=card]:border-0 in-data-[slot=card]:bg-transparent in-data-[slot=card]:py-10',
        className,
      )}
    >
      <div className="mb-4 flex size-9 items-center justify-center rounded-lg border border-destructive/25 bg-destructive/10 text-destructive">
        <CircleAlert className="size-4" aria-hidden />
      </div>
      <h3 className="text-[0.9375rem] leading-snug font-medium tracking-[-0.01em]">{title}</h3>
      <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted-foreground">{errorMessage(error)}</p>
      {requestId && (
        <p className="mt-3 font-mono text-[0.75rem] text-muted-foreground">
          Request ID <span className="text-foreground">{requestId}</span>
        </p>
      )}
      {onRetry && (
        <Button variant="outline" className="mt-5" onClick={onRetry}>
          <RotateCw aria-hidden /> Try again
        </Button>
      )}
    </div>
  )
}
