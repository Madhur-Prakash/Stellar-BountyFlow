import { CircleAlert, RotateCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { errorMessage, isApiError } from '@/lib/api/client'
import { cn } from '@/lib/utils'

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
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-destructive/25 bg-destructive/5 px-6 py-10 text-center',
        className,
      )}
    >
      <CircleAlert className="mb-3 size-6 text-destructive" aria-hidden />
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm text-muted-foreground">{errorMessage(error)}</p>
      {requestId && <p className="mt-2 font-mono text-xs text-muted-foreground">Request ID {requestId}</p>}
      {onRetry && (
        <Button variant="outline" className="mt-5" onClick={onRetry}>
          <RotateCw /> Try again
        </Button>
      )}
    </div>
  )
}
