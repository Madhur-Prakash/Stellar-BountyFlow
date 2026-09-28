import { Skeleton } from '@/components/ui/skeleton'

export function BountyCardSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-5 shadow-soft" aria-hidden>
      <div className="flex items-center justify-between">
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-5 w-20" />
      </div>
      <Skeleton className="mt-4 h-5 w-4/5" />
      <Skeleton className="mt-2 h-4 w-full" />
      <Skeleton className="mt-1.5 h-4 w-3/5" />
      <div className="mt-4 flex gap-1.5">
        <Skeleton className="h-6 w-14" />
        <Skeleton className="h-6 w-16" />
        <Skeleton className="h-6 w-12" />
      </div>
      <div className="mt-5 flex items-end justify-between border-t pt-4">
        <Skeleton className="h-7 w-28" />
        <Skeleton className="h-4 w-24" />
      </div>
    </div>
  )
}

export function BountyGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div role="status" aria-live="polite" aria-label="Loading bounties">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: count }, (_, i) => (
          <BountyCardSkeleton key={i} />
        ))}
      </div>
      <span className="sr-only">Loading bounties…</span>
    </div>
  )
}
