import { Skeleton } from '@/components/ui/skeleton'

export function BountyCardSkeleton() {
  return (
    <div className="flex h-full flex-col rounded-xl border bg-card p-5 shadow-soft" aria-hidden>
      <div className="flex min-h-7 items-start gap-1.5">
        <Skeleton className="h-5.5 w-24" />
        <Skeleton className="h-5.5 w-14" />
      </div>
      <Skeleton className="mt-2.5 h-5 w-4/5" />
      <Skeleton className="mt-2 h-4 w-full" />
      <Skeleton className="mt-1.5 h-4 w-3/5" />
      <Skeleton className="mt-3.5 h-3.5 w-48" />
      <div className="mt-3 flex gap-1">
        <Skeleton className="h-5.5 w-14" />
        <Skeleton className="h-5.5 w-16" />
        <Skeleton className="h-5.5 w-12" />
      </div>
      <div className="mt-4 flex items-end justify-between border-t pt-4">
        <Skeleton className="h-6 w-24" />
        <div className="flex flex-col items-end gap-1.5">
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="h-3.5 w-16" />
        </div>
      </div>
      <Skeleton className="mt-3.5 h-4 w-28" />
    </div>
  )
}

export function BountyGridSkeleton({ count = 6, className }: { count?: number; className?: string }) {
  return (
    <div role="status" aria-live="polite" aria-label="Loading bounties">
      <div className={className ?? 'grid gap-4 sm:grid-cols-2 xl:grid-cols-3'}>
        {Array.from({ length: count }, (_, i) => (
          <BountyCardSkeleton key={i} />
        ))}
      </div>
      <span className="sr-only">Loading bounties…</span>
    </div>
  )
}
