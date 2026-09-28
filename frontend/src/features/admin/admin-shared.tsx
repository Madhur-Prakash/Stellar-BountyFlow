import type { UseQueryResult } from '@tanstack/react-query'
import {
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  CircleMinus,
  Clock3,
  Eye,
  Gavel,
  LoaderCircle,
  Search,
  SearchX,
  ShieldCheck,
  TriangleAlert,
  UserCog,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react'
import { Fragment, useState, type MouseEvent, type ReactNode } from 'react'
import { Link } from 'react-router'

import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { PaginationBar } from '@/components/layout/PaginationBar'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardFooter } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { DisputeStatus, Page, ReportStatus, Role, UserSummary } from '@/lib/api/types'
import {
  DISPUTE_STATUS_LABELS,
  formatDate,
  formatDateTime,
  formatNumber,
  humanize,
  REPORT_STATUS_LABELS,
} from '@/lib/format'
import { cn } from '@/lib/utils'

import { ADMIN_PAGE_SIZE, ALL_OPTION, ROLE_LABELS } from './admin-utils'

type BadgeVariant = 'warning' | 'danger' | 'info' | 'outline'

// ---------------------------------------------------------------------------
// Toolbar filters
// ---------------------------------------------------------------------------

/** Labelled text filter with a leading icon and a clear button. */
export function SearchField({
  id,
  label,
  value,
  onChange,
  placeholder,
  maxLength = 100,
  icon: Icon = Search,
  list,
  className,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  maxLength?: number
  icon?: LucideIcon
  /** Optional <datalist> id with suggestions. */
  list?: string
  className?: string
}) {
  return (
    <div className={cn('relative w-full min-w-0 sm:w-72', className)}>
      <Label htmlFor={id} className="sr-only">
        {label}
      </Label>
      <Icon
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <Input
        id={id}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        autoComplete="off"
        spellCheck={false}
        list={list}
        className="pr-9 pl-9 [&::-webkit-search-cancel-button]:hidden"
      />
      {value && (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="absolute top-1/2 right-0.5 -translate-y-1/2 text-muted-foreground"
          aria-label={`Clear ${label.toLowerCase()}`}
          onClick={() => onChange('')}
        >
          <X />
        </Button>
      )}
    </div>
  )
}

/** Labelled enum filter; `undefined` means "all" (rendered with a sentinel value). */
export function FilterSelect<T extends string>({
  id,
  label,
  value,
  onChange,
  options,
  labels,
  allLabel,
  className,
}: {
  id: string
  label: string
  value: T | undefined
  onChange: (value: T | undefined) => void
  options: readonly T[]
  labels?: Partial<Record<T, string>>
  allLabel: string
  className?: string
}) {
  return (
    <div className={cn('w-full sm:w-44', className)}>
      <Label htmlFor={id} className="sr-only">
        {label}
      </Label>
      <Select
        value={value ?? ALL_OPTION}
        onValueChange={(v) => onChange(v === ALL_OPTION ? undefined : (v as T))}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_OPTION}>{allLabel}</SelectItem>
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {labels?.[o] ?? humanize(o)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Paged list card
// ---------------------------------------------------------------------------

type EmptyConfig = { icon?: LucideIcon; title: string; description?: ReactNode }

/** Row placeholders shown until a list's captured bones exist. */
function RowsSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="divide-y">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-11 items-center gap-4 px-4">
          <Skeleton className="size-7 shrink-0 rounded-full" />
          <Skeleton className="h-3.5 w-40" />
          <Skeleton className="hidden h-3.5 w-48 md:block" />
          <Skeleton className="ml-auto h-5 w-16" />
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  )
}

/**
 * One card per admin list: a toolbar (filters and the result count), the rows, and pagination in the footer.
 * Handles loading (boneyard bones named by `skeleton`), error and empty states for a `Page<T>` query.
 * `filtered` switches the empty state to "no matches" with a clear-filters action.
 */
export function PagedResults<T>({
  query,
  label,
  itemLabel,
  errorTitle,
  empty,
  filtered = false,
  onClearFilters,
  onPageChange,
  skeleton,
  toolbar,
  children,
}: {
  query: UseQueryResult<Page<T>>
  /** Accessible name of the results region. */
  label: string
  itemLabel: string
  errorTitle: string
  empty: EmptyConfig
  filtered?: boolean
  onClearFilters?: () => void
  onPageChange: (page: number) => void
  skeleton: string
  /** Filters, rendered in the card's toolbar. */
  toolbar?: ReactNode
  children: (items: T[]) => ReactNode
}) {
  const data = query.data
  const emptyClass = 'rounded-none border-0 bg-transparent py-14'

  let body: ReactNode
  if (query.isError) {
    body = (
      <ErrorState error={query.error} title={errorTitle} onRetry={() => query.refetch()} className="m-4" />
    )
  } else if (data && data.total === 0) {
    body = filtered ? (
      <EmptyState
        icon={SearchX}
        title={`No ${itemLabel} match these filters`}
        className={emptyClass}
        action={
          onClearFilters ? (
            <Button variant="outline" onClick={onClearFilters}>
              Clear filters
            </Button>
          ) : undefined
        }
      />
    ) : (
      <EmptyState {...empty} className={emptyClass} />
    )
  } else {
    body = (
      <Bones name={skeleton} loading={query.isPending} fallback={<RowsSkeleton />}>
        {data ? (
          data.items.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="Nothing on this page"
              className={emptyClass}
              action={
                <Button variant="outline" onClick={() => onPageChange(1)}>
                  Back to first page
                </Button>
              }
            />
          ) : (
            <>
              <div className={cn('transition-opacity', query.isPlaceholderData && 'opacity-60')}>
                {children(data.items)}
              </div>
              {data.pages > 1 && (
                <CardFooter className="px-4 py-2.5">
                  <PaginationBar
                    className="w-full pt-0"
                    page={data.page}
                    pages={data.pages}
                    total={data.total}
                    pageSize={data.page_size || ADMIN_PAGE_SIZE}
                    itemLabel={itemLabel}
                    onPageChange={onPageChange}
                  />
                </CardFooter>
              )}
            </>
          )
        ) : null}
      </Bones>
    )
  }

  return (
    <Card className="gap-0 py-0">
      <div className="flex flex-col gap-2.5 border-b px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center">
        {toolbar && (
          <div role="search" className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            {toolbar}
          </div>
        )}
        <p
          aria-live="polite"
          className="flex items-center gap-1.5 text-[0.8125rem] text-muted-foreground tabular-nums sm:ml-auto"
        >
          {query.isFetching && !query.isPending && (
            <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
          )}
          {data && data.total > 0 ? `${formatNumber(data.total)} ${itemLabel}` : null}
        </p>
      </div>
      <section aria-label={label} aria-busy={query.isFetching}>
        {body}
      </section>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Dense table (desktop) with stacked rows (below lg)
// ---------------------------------------------------------------------------

export type AdminColumn<T> = {
  key: string
  header: string
  cell: (row: T) => ReactNode
  /** Extra classes for both <th> and <td> (e.g. "text-right"). */
  className?: string
  /** Visually hide the column header (it stays available to screen readers). */
  hideHeader?: boolean
  /**
   * Where the column goes in a stacked row: the `title` line, the top-right `aside`, a labelled `field` (the
   * default), the bottom `actions` row, or `hidden`.
   */
  mobile?: 'title' | 'aside' | 'field' | 'actions' | 'hidden'
  /** Let a stacked-row field use the full row width. */
  wide?: boolean
  /** Only show this column in stacked rows (the table shows it inside another cell). */
  desktopHidden?: boolean
  /** Position among a stacked row's fields (defaults to the column order). */
  mobileOrder?: number
}

const INTERACTIVE = 'a, button, input, select, textarea, label, [role="combobox"], [role="menuitem"]'

/**
 * Admin records: a real <table> from lg up (44px rows, scrolls inside its container if needed) and stacked rows
 * below that. With `detail`, every row expands to show more (a chevron button, or a click on the row).
 */
export function AdminTable<T>({
  rows,
  columns,
  getKey,
  caption,
  detail,
  detailLabel,
}: {
  rows: T[]
  columns: AdminColumn<T>[]
  getKey: (row: T) => string
  caption: string
  detail?: (row: T) => ReactNode
  /** Accessible name of the expand button, e.g. "Show details for …". */
  detailLabel?: (row: T) => string
}) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set())
  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const place = (c: AdminColumn<T>) => c.mobile ?? 'field'
  const titleCols = columns.filter((c) => place(c) === 'title')
  const asideCols = columns.filter((c) => place(c) === 'aside')
  const fieldCols = columns
    .map((c, i) => ({ c, order: c.mobileOrder ?? i }))
    .filter(({ c }) => place(c) === 'field')
    .sort((a, b) => a.order - b.order)
    .map(({ c }) => c)
  const actionCols = columns.filter((c) => place(c) === 'actions')
  const tableCols = columns.filter((c) => !c.desktopHidden)
  const colCount = tableCols.length + (detail ? 1 : 0)

  const onRowClick = (key: string) => (e: MouseEvent<HTMLTableRowElement>) => {
    if (!detail) return
    if ((e.target as HTMLElement).closest(INTERACTIVE)) return
    if (window.getSelection()?.toString()) return
    toggle(key)
  }

  return (
    <>
      <div className="hidden lg:block">
        <Table className="[&_td:first-child]:pl-4 [&_td:last-child]:pr-4 [&_th:first-child]:pl-4 [&_th:last-child]:pr-4">
          <caption className="sr-only">{caption}</caption>
          <TableHeader className="bg-surface/60">
            <TableRow className="hover:bg-transparent">
              {detail && (
                <TableHead className="w-10 pr-0">
                  <span className="sr-only">Details</span>
                </TableHead>
              )}
              {tableCols.map((c) => (
                <TableHead key={c.key} className={c.className}>
                  {c.hideHeader ? <span className="sr-only">{c.header}</span> : c.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const key = getKey(row)
              const open = expanded.has(key)
              const panelId = `admin-detail-${key}`
              return (
                <Fragment key={key}>
                  <TableRow
                    className={cn(detail && 'cursor-pointer', open && 'border-b-0 bg-muted/40')}
                    onClick={detail ? onRowClick(key) : undefined}
                  >
                    {detail && (
                      <TableCell className="w-10 py-1 pr-0">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="text-muted-foreground"
                          aria-label={detailLabel?.(row) ?? 'Show details'}
                          aria-expanded={open}
                          aria-controls={open ? panelId : undefined}
                          onClick={() => toggle(key)}
                        >
                          <ChevronRight className={cn('transition-transform', open && 'rotate-90')} />
                        </Button>
                      </TableCell>
                    )}
                    {tableCols.map((c) => (
                      <TableCell key={c.key} className={cn('py-1', c.className)}>
                        {c.cell(row)}
                      </TableCell>
                    ))}
                  </TableRow>
                  {detail && open && (
                    <TableRow id={panelId} className="bg-muted/40 hover:bg-muted/40">
                      <TableCell colSpan={colCount} className="h-auto p-0 whitespace-normal">
                        {detail(row)}
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      </div>

      <ul className="divide-y lg:hidden" aria-label={caption}>
        {rows.map((row) => {
          const key = getKey(row)
          const open = expanded.has(key)
          const panelId = `admin-detail-m-${key}`
          return (
            <li key={key} className="px-4 py-3.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  {titleCols.map((c) => (
                    <div key={c.key} className="min-w-0">
                      {c.cell(row)}
                    </div>
                  ))}
                </div>
                {asideCols.length > 0 && (
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    {asideCols.map((c) => (
                      <Fragment key={c.key}>{c.cell(row)}</Fragment>
                    ))}
                  </div>
                )}
              </div>
              {fieldCols.length > 0 && (
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
                  {fieldCols.map((c) => (
                    <div key={c.key} className={cn('min-w-0', c.wide && 'col-span-2')}>
                      <dt className="text-xs text-muted-foreground">{c.header}</dt>
                      <dd className="mt-0.5 min-w-0">{c.cell(row)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {actionCols.map((c) => (
                <div key={c.key} className="mt-3 flex flex-wrap items-center gap-2">
                  {c.cell(row)}
                </div>
              ))}
              {detail && (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="mt-2 -ml-2 text-muted-foreground"
                    aria-label={detailLabel?.(row) ?? 'Show details'}
                    aria-expanded={open}
                    aria-controls={open ? panelId : undefined}
                    onClick={() => toggle(key)}
                  >
                    <ChevronRight className={cn('transition-transform', open && 'rotate-90')} aria-hidden />
                    Details
                  </Button>
                  {open && (
                    <div id={panelId} className="-mx-4 mt-2 border-t bg-muted/40">
                      {detail(row)}
                    </div>
                  )}
                </>
              )}
            </li>
          )
        })}
      </ul>
    </>
  )
}

// ---------------------------------------------------------------------------
// Cells & badges
// ---------------------------------------------------------------------------

/** Avatar, display name, and @username linking to the public profile. */
export function UserCell({
  user,
  avatar = true,
  className,
}: {
  user: UserSummary
  /** Leave the avatar out in secondary columns of wide tables. */
  avatar?: boolean
  className?: string
}) {
  return (
    <span className={cn('inline-flex max-w-full min-w-0 items-center gap-2.5 text-left', className)}>
      {avatar && <UserAvatar user={user} className="size-7" />}
      <span className="min-w-0">
        <span className="block truncate leading-5 font-medium">{user.display_name || user.username}</span>
        <Link
          to={`/u/${encodeURIComponent(user.username)}`}
          className="block truncate text-xs leading-4 text-muted-foreground hover:text-foreground hover:underline"
        >
          @{user.username}
        </Link>
      </span>
    </span>
  )
}

/** One line in the table (two in stacked rows), with the full text on hover. */
export function ClampedText({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text) return <span className="text-muted-foreground">—</span>
  return (
    <p
      className={cn(
        'line-clamp-2 max-w-72 text-sm wrap-break-word whitespace-normal lg:line-clamp-1',
        className,
      )}
      title={text}
    >
      {text}
    </p>
  )
}

/** Date with the full date-time in a tooltip. */
export function DateCell({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="text-muted-foreground">—</span>
  return (
    <time
      dateTime={iso}
      title={formatDateTime(iso)}
      className="whitespace-nowrap text-muted-foreground tabular-nums"
    >
      {formatDate(iso)}
    </time>
  )
}

const ROLE_BADGE: Record<Role, { variant: BadgeVariant; icon: LucideIcon }> = {
  USER: { variant: 'outline', icon: UserRound },
  MODERATOR: { variant: 'outline', icon: ShieldCheck },
  ADMIN: { variant: 'info', icon: UserCog },
}

export function RoleBadge({ role }: { role: Role }) {
  const { variant, icon: Icon } = ROLE_BADGE[role]
  return (
    <Badge variant={variant}>
      <Icon aria-hidden />
      {ROLE_LABELS[role]}
    </Badge>
  )
}

const REPORT_BADGE: Record<ReportStatus, { variant: BadgeVariant; icon: LucideIcon }> = {
  OPEN: { variant: 'warning', icon: CircleAlert },
  REVIEWING: { variant: 'info', icon: Eye },
  ACTIONED: { variant: 'outline', icon: Gavel },
  DISMISSED: { variant: 'outline', icon: CircleMinus },
}

export function ReportStatusBadge({ status }: { status: ReportStatus }) {
  const { variant, icon: Icon } = REPORT_BADGE[status]
  return (
    <Badge variant={variant}>
      <Icon aria-hidden />
      {REPORT_STATUS_LABELS[status]}
    </Badge>
  )
}

const DISPUTE_BADGE: Record<DisputeStatus, { variant: BadgeVariant; icon: LucideIcon }> = {
  OPEN: { variant: 'warning', icon: CircleAlert },
  UNDER_REVIEW: { variant: 'info', icon: Clock3 },
  RESOLVED: { variant: 'outline', icon: CheckCircle2 },
  DISMISSED: { variant: 'outline', icon: CircleMinus },
}

export function DisputeStatusBadge({ status }: { status: DisputeStatus }) {
  const { variant, icon: Icon } = DISPUTE_BADGE[status]
  return (
    <Badge variant={variant}>
      <Icon aria-hidden />
      {DISPUTE_STATUS_LABELS[status]}
    </Badge>
  )
}

const HEALTH_BADGE: Record<
  string,
  { variant: BadgeVariant; icon: LucideIcon; label: string; tone?: string }
> = {
  ok: { variant: 'outline', icon: CheckCircle2, label: 'OK', tone: 'text-success' },
  error: { variant: 'danger', icon: CircleAlert, label: 'Error' },
  disabled: { variant: 'outline', icon: CircleMinus, label: 'Disabled', tone: 'text-muted-foreground' },
  degraded: { variant: 'warning', icon: TriangleAlert, label: 'Degraded' },
}

/** Badge for a health check state ("ok" | "error" | "disabled" | "degraded"). */
export function HealthBadge({ state }: { state: string }) {
  const known = HEALTH_BADGE[state]
  if (!known) return <Badge variant="outline">{humanize(state)}</Badge>
  const Icon = known.icon
  return (
    <Badge variant={known.variant}>
      <Icon className={known.tone} aria-hidden />
      {known.label}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Confirmation
// ---------------------------------------------------------------------------

/**
 * Yes/no confirmation that stays open while `onConfirm` runs. `onConfirm`
 * is responsible for closing the dialog on success.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive = false,
  pending = false,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: ReactNode
  confirmLabel: string
  destructive?: boolean
  pending?: boolean
  onConfirm: () => void
}) {
  return (
    <AlertDialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant={destructive ? 'destructive' : 'default'}
            disabled={pending}
            onClick={(e) => {
              e.preventDefault()
              onConfirm()
            }}
          >
            {pending && <LoaderCircle className="animate-spin" aria-hidden />}
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
