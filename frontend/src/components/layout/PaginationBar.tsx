import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'

function pageWindow(page: number, pages: number): (number | 'gap')[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1)
  const out: (number | 'gap')[] = [1]
  const start = Math.max(2, page - 1)
  const end = Math.min(pages - 1, page + 1)
  if (start > 2) out.push('gap')
  for (let p = start; p <= end; p++) out.push(p)
  if (end < pages - 1) out.push('gap')
  out.push(pages)
  return out
}

export function PaginationBar({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
  className,
  itemLabel = 'results',
}: {
  page: number
  pages: number
  total: number
  pageSize: number
  onPageChange: (page: number) => void
  className?: string
  itemLabel?: string
}) {
  if (total === 0) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <nav
      aria-label="Pagination"
      className={cn('flex flex-col items-center justify-between gap-3 pt-6 sm:flex-row', className)}
    >
      <p className="text-sm text-muted-foreground tabular-nums">
        Showing {formatNumber(from)}–{formatNumber(to)} of {formatNumber(total)} {itemLabel}
      </p>
      {pages > 1 && (
        <ul className="flex items-center gap-1">
          <li>
            <Button
              variant="ghost"
              size="icon"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
              aria-label="Previous page"
            >
              <ChevronLeft />
            </Button>
          </li>
          {pageWindow(page, pages).map((p, i) =>
            p === 'gap' ? (
              <li key={`gap-${i}`} aria-hidden className="px-1 text-muted-foreground">
                …
              </li>
            ) : (
              <li key={p} className="hidden sm:block">
                <Button
                  variant={p === page ? 'outline' : 'ghost'}
                  size="icon"
                  onClick={() => onPageChange(p)}
                  aria-label={`Page ${p}`}
                  aria-current={p === page ? 'page' : undefined}
                  className="tabular-nums"
                >
                  {p}
                </Button>
              </li>
            ),
          )}
          <li className="px-2 text-sm text-muted-foreground tabular-nums sm:hidden">
            {page} / {pages}
          </li>
          <li>
            <Button
              variant="ghost"
              size="icon"
              disabled={page >= pages}
              onClick={() => onPageChange(page + 1)}
              aria-label="Next page"
            >
              <ChevronRight />
            </Button>
          </li>
        </ul>
      )}
    </nav>
  )
}
