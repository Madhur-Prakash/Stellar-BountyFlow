import type { UseQueryResult } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Bones } from './Bones'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { ListSkeleton } from './LoadingState'

/**
 * Standard loading / error / empty handling for a query.
 * `isEmpty` decides when to render the empty state; `children` receives data.
 * With `skeleton`, loading shows boneyard bones captured from this view's real layout (see Bones); `loading` is
 * then the fallback for views or breakpoints without captured bones.
 */
export function QueryView<T>({
  query,
  isEmpty,
  empty,
  errorTitle,
  loading,
  skeleton,
  children,
}: {
  query: UseQueryResult<T>
  isEmpty?: (data: T) => boolean
  empty?: { icon?: LucideIcon; title: string; description?: ReactNode; action?: ReactNode }
  errorTitle?: string
  loading?: ReactNode
  skeleton?: string
  children: (data: T) => ReactNode
}) {
  if (query.isError)
    return <ErrorState error={query.error} title={errorTitle} onRetry={() => query.refetch()} />
  if (!query.isPending && empty && isEmpty?.(query.data)) return <EmptyState {...empty} />
  if (skeleton) {
    return (
      <Bones name={skeleton} loading={query.isPending} fallback={loading ?? <ListSkeleton rows={4} />}>
        {query.isPending ? null : children(query.data)}
      </Bones>
    )
  }
  if (query.isPending) return <>{loading ?? <ListSkeleton rows={4} />}</>
  return <>{children(query.data)}</>
}
