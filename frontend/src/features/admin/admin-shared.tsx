import type { UseQueryResult } from '@tanstack/react-query'
import {
  CheckCircle2,
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
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { UserAvatar } from '@/components/common/UserAvatar'
import { EmptyState } from '@/components/layout/EmptyState'
import { ListSkeleton } from '@/components/layout/LoadingState'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { DisputeStatus, Page, ReportStatus, Role, UserSummary } from '@/lib/api/types'
import {
  DISPUTE_STATUS_LABELS,
  formatDate,
  formatDateTime,
  humanize,
  REPORT_STATUS_LABELS,
} from '@/lib/format'
import { cn } from '@/lib/utils'

import { ADMIN_PAGE_SIZE, ALL_OPTION, ROLE_LABELS } from './admin-utils'

type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'cyan' | 'outline'

// ---------------------------------------------------------------------------
// Filters
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
    <div className={cn('relative min-w-0 flex-1', className)}>
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
        className="pr-11 pl-9 [&::-webkit-search-cancel-button]:hidden"
      />
      {value && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute top-1/2 right-0 -translate-y-1/2"
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
    <div className={cn('w-full md:w-56', className)}>
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

/** Row of filters above an admin list. */
export function FilterBar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      role="search"
      className={cn('mb-5 flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center', className)}
    >
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Paged list wrapper
// ---------------------------------------------------------------------------

type EmptyConfig = { icon?: LucideIcon; title: string; description?: ReactNode }

/**
 * Loading / error / empty handling plus pagination for a `Page<T>` query.
 * `filtered` switches the empty state to a "no matches" message with a
 * clear-filters action. `skeleton` names the list's captured loading bones (see QueryView).
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
  skeleton?: string
  children: (items: T[]) => ReactNode
}) {
  const emptyState = filtered
    ? {
        icon: SearchX,
        title: `No ${itemLabel} match these filters`,
        description: 'Try a broader search or clear the filters.',
        action: onClearFilters ? (
          <Button variant="outline" onClick={onClearFilters}>
            Clear filters
          </Button>
        ) : undefined,
      }
    : empty

  return (
    <section aria-label={label} aria-busy={query.isFetching}>
      <QueryView
        query={query}
        errorTitle={errorTitle}
        loading={<ListSkeleton rows={6} />}
        skeleton={skeleton}
        isEmpty={(data) => data.total === 0}
        empty={emptyState}
      >
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="Nothing on this page"
              description={`This page is past the last page of ${itemLabel}.`}
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
              <PaginationBar
                page={data.page}
                pages={data.pages}
                total={data.total}
                pageSize={data.page_size || ADMIN_PAGE_SIZE}
                itemLabel={itemLabel}
                onPageChange={onPageChange}
              />
            </>
          )
        }
      </QueryView>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Cells & badges
// ---------------------------------------------------------------------------

/** Avatar, display name, and @username linking to the public profile. */
export function UserCell({ user, className }: { user: UserSummary; className?: string }) {
  return (
    <span className={cn('inline-flex max-w-full min-w-0 items-center gap-2.5 text-left', className)}>
      <UserAvatar user={user} />
      <span className="min-w-0">
        <span className="block truncate font-medium">{user.display_name || user.username}</span>
        <Link
          to={`/u/${encodeURIComponent(user.username)}`}
          className="block truncate text-xs text-muted-foreground hover:text-foreground hover:underline"
        >
          @{user.username}
        </Link>
      </span>
    </span>
  )
}

/** Clamped text with the full value available on hover and to screen readers. */
export function ClampedText({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text) return <span className="text-muted-foreground">—</span>
  return (
    <p
      className={cn('line-clamp-2 max-w-xs text-sm break-words whitespace-pre-line', className)}
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
  USER: { variant: 'muted', icon: UserRound },
  MODERATOR: { variant: 'info', icon: ShieldCheck },
  ADMIN: { variant: 'cyan', icon: UserCog },
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
  ACTIONED: { variant: 'success', icon: Gavel },
  DISMISSED: { variant: 'muted', icon: CircleMinus },
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
  OPEN: { variant: 'danger', icon: CircleAlert },
  UNDER_REVIEW: { variant: 'info', icon: Clock3 },
  RESOLVED: { variant: 'success', icon: CheckCircle2 },
  DISMISSED: { variant: 'muted', icon: CircleMinus },
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

const HEALTH_BADGE: Record<string, { variant: BadgeVariant; icon: LucideIcon; label: string }> = {
  ok: { variant: 'success', icon: CheckCircle2, label: 'OK' },
  error: { variant: 'danger', icon: CircleAlert, label: 'Error' },
  disabled: { variant: 'muted', icon: CircleMinus, label: 'Disabled' },
  degraded: { variant: 'warning', icon: TriangleAlert, label: 'Degraded' },
}

/** Badge for a health check state ("ok" | "error" | "disabled" | "degraded"). */
export function HealthBadge({ state }: { state: string }) {
  const known = HEALTH_BADGE[state]
  if (!known) return <Badge variant="outline">{humanize(state)}</Badge>
  const Icon = known.icon
  return (
    <Badge variant={known.variant}>
      <Icon aria-hidden />
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
