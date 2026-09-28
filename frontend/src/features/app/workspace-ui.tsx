import type { UseQueryResult } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

/** The row above a card's list: tabs or filters on the left, secondary controls on the right. */
export function CardToolbar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'flex min-w-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-5',
        className,
      )}
    >
      {children}
    </div>
  )
}

/** Placeholder rows for a list that sits flush inside a card. */
export function RowsSkeleton({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading" className={cn('divide-y', className)}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-14 items-center gap-4 px-4 sm:px-5">
          <Skeleton className="h-4 w-2/5 max-w-72" />
          <Skeleton className="ml-auto hidden h-4 w-20 sm:block" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  )
}

type Empty = { icon?: LucideIcon; title: string; description?: ReactNode; action?: ReactNode }

/**
 * Loading, error and empty handling for results shown inside a card: the same order as QueryView, but the
 * empty state and error sit flush in the card instead of drawing a second box.
 */
export function CardQuery<T>({
  query,
  skeleton,
  isEmpty,
  empty,
  errorTitle,
  rows,
  children,
}: {
  query: UseQueryResult<T>
  skeleton: string
  isEmpty?: (data: T) => boolean
  empty?: Empty
  errorTitle?: string
  rows?: number
  children: (data: T) => ReactNode
}) {
  if (query.isError)
    return (
      <div className="p-4 sm:p-5">
        <ErrorState error={query.error} title={errorTitle} onRetry={() => void query.refetch()} />
      </div>
    )
  if (!query.isPending && empty && isEmpty?.(query.data))
    return <EmptyState {...empty} className="rounded-none border-0 bg-transparent py-14" />
  return (
    <Bones name={skeleton} loading={query.isPending} fallback={<RowsSkeleton rows={rows} />}>
      {query.isPending ? null : children(query.data)}
    </Bones>
  )
}

export type Column<T> = {
  key: string
  header: ReactNode
  cell: (row: T) => ReactNode
  /** Classes for both the header and the cells of this column (e.g. "text-right"). */
  className?: string
}

const STACK_BELOW = {
  md: { table: 'hidden md:block', list: 'md:hidden' },
  lg: { table: 'hidden lg:block', list: 'lg:hidden' },
} as const

/**
 * Records inside a card: a table from `stackBelow` up and stacked rows below it. Both are flush with the card
 * edges; the mobile list keeps the caption as its accessible name.
 */
export function ResponsiveTable<T>({
  caption,
  rows,
  getKey,
  columns,
  renderMobile,
  stackBelow = 'md',
}: {
  caption: string
  rows: T[]
  getKey: (row: T) => string
  columns: Column<T>[]
  renderMobile: (row: T) => ReactNode
  stackBelow?: keyof typeof STACK_BELOW
}) {
  const bp = STACK_BELOW[stackBelow]
  return (
    <>
      <div className={bp.table}>
        <Table>
          <caption className="sr-only">{caption}</caption>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {columns.map((c) => (
                <TableHead key={c.key} className={cn('first:pl-5 last:pr-5', c.className)}>
                  {c.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={getKey(row)}>
                {columns.map((c) => (
                  <TableCell key={c.key} className={cn('first:pl-5 last:pr-5', c.className)}>
                    {c.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul aria-label={caption} className={cn('divide-y', bp.list)}>
        {rows.map((row) => (
          <li key={getKey(row)} className="min-w-0 px-4 py-3.5">
            {renderMobile(row)}
          </li>
        ))}
      </ul>
    </>
  )
}

/** A money figure: tabular amount with its asset code, right-aligned by the caller. */
export function Money({ amount, asset }: { amount: ReactNode; asset: string }) {
  return (
    <span className="whitespace-nowrap">
      <span className="amount">{amount}</span> <span className="text-xs text-muted-foreground">{asset}</span>
    </span>
  )
}

/** Keeps the chart's space while the chart module loads, so nothing shifts when it arrives. */
export function ChartFallback({ height }: { height: number }) {
  return <Skeleton className="w-full rounded-lg" style={{ height }} />
}

/** An empty chart area. Pass the height as classes so it can be shorter on small screens. */
export function ChartEmpty({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        'flex items-center justify-center rounded-lg border border-dashed px-6 text-center text-sm text-muted-foreground',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function ChartCard({
  title,
  description,
  className,
  children,
}: {
  title: string
  description?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <Card className={cn('min-w-0', className)}>
      <CardHeader>
        <CardTitle>
          <h3>{title}</h3>
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}
