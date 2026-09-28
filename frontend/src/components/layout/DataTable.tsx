import type { ReactNode } from 'react'

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

export type Column<T> = {
  key: string
  header: string
  cell: (row: T) => ReactNode
  /** Extra classes for both <th> and <td> (e.g. "text-right"). */
  className?: string
  /** Hide this column's label in the mobile card (e.g. for action buttons). */
  hideLabelOnMobile?: boolean
  /** Leave this column out of the mobile card (e.g. it duplicates `mobileTitle`). */
  mobileHidden?: boolean
}

/**
 * Overflow-safe table: a real <table> from lg up (horizontally scrollable if needed), and label/value cards below
 * that (two per row on tablets), so action columns are never hidden behind a horizontal scroll.
 *
 * On the canvas the table sits in its own bordered panel; inside a Card it runs edge to edge with the card.
 */
export function DataTable<T>({
  rows,
  columns,
  getKey,
  caption,
  mobileTitle,
}: {
  rows: T[]
  columns: Column<T>[]
  getKey: (row: T) => string
  caption: string
  /** Prominent first line of each mobile card. */
  mobileTitle?: (row: T) => ReactNode
}) {
  return (
    <>
      <div
        data-slot="data-table"
        className="hidden overflow-hidden rounded-xl border bg-card shadow-soft in-data-[slot=card]:rounded-none in-data-[slot=card]:border-x-0 in-data-[slot=card]:border-b-0 in-data-[slot=card]:shadow-none lg:block"
      >
        <Table>
          <caption className="sr-only">{caption}</caption>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {columns.map((c) => (
                <TableHead key={c.key} className={c.className}>
                  {c.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={getKey(row)}>
                {columns.map((c) => (
                  <TableCell key={c.key} className={cn('align-middle', c.className)}>
                    {c.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="grid gap-2.5 sm:grid-cols-2 sm:gap-3 lg:hidden" aria-label={caption}>
        {rows.map((row) => (
          <li
            key={getKey(row)}
            className="min-w-0 overflow-hidden rounded-lg border bg-card shadow-soft in-data-[slot=card]:shadow-none"
          >
            {mobileTitle && (
              <div className="border-b px-4 py-3 text-sm leading-snug font-medium">{mobileTitle(row)}</div>
            )}
            <dl className="space-y-2 px-4 py-3">
              {columns
                .filter((c) => !c.mobileHidden)
                .map((c) => (
                  <div key={c.key} className="flex items-start justify-between gap-3 text-sm">
                    {!c.hideLabelOnMobile && (
                      <dt className="shrink-0 text-[0.8125rem] text-muted-foreground">{c.header}</dt>
                    )}
                    <dd className={cn('min-w-0 text-right', c.hideLabelOnMobile && 'w-full text-left')}>
                      {c.cell(row)}
                    </dd>
                  </div>
                ))}
            </dl>
          </li>
        ))}
      </ul>
    </>
  )
}
