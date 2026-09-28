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
        'flex flex-col items-center justify-center rounded-xl border border-destructive/20 bg-destructive/3 px-6 py-10 text-center',
        'in-data-[slot=card]:rounded-none in-data-[slot=card]:border-0 in-data-[slot=card]:bg-transparent in-data-[slot=card]:py-8',
        className,
      )}
    >
      <div className="mb-3 flex size-10 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
        <CircleAlert className="size-5" aria-hidden />
      </div>
      <h3 className="text-[0.9375rem] font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{errorMessage(error)}</p>
      {requestId && <p className="mt-2 font-mono text-xs text-muted-foreground">Request ID {requestId}</p>}
      {onRetry && (
        <Button variant="outline" className="mt-4" onClick={onRetry}>
          <RotateCw aria-hidden /> Try again
        </Button>
      )}
    </div>
  )
}
