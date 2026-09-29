import {
  Bug,
  CircleCheck,
  CircleDot,
  Lightbulb,
  MessageSquare,
  MessageSquareText,
  ThumbsUp,
  Undo2,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ReasonDialog } from '@/components/common/ReasonDialog'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api/client'
import { useMe } from '@/lib/api/queries/auth'
import { useAdminFeedback, useHandleFeedback } from '@/lib/api/queries/feedback'
import {
  FEEDBACK_KINDS,
  FEEDBACK_STATUSES,
  type Feedback,
  type FeedbackKind,
  type FeedbackStatus,
} from '@/lib/api/types'
import {
  FEEDBACK_KIND_LABELS,
  FEEDBACK_STATUS_LABELS,
  formatDateTime,
  formatNumber,
  formatRelative,
} from '@/lib/format'
import { hasPermission } from '@/lib/permissions'
import { describeUserAgent } from '@/lib/user-agent'

import {
  AdminTable,
  ClampedText,
  DateCell,
  FilterSelect,
  PagedResults,
  UserCell,
  type AdminColumn,
} from './admin-shared'
import { ADMIN_PAGE_SIZE, scrollToTop, useFilteredPage } from './admin-utils'

/** Enough of a note to recognise it in the confirmation. */
function excerpt(message: string): string {
  return message.length > 140 ? `${message.slice(0, 140).trimEnd()}…` : message
}

const KIND_ICONS: Record<FeedbackKind, LucideIcon> = {
  BUG: Bug,
  IDEA: Lightbulb,
  PRAISE: ThumbsUp,
  OTHER: MessageSquare,
}

function KindBadge({ kind }: { kind: FeedbackKind }) {
  const Icon = KIND_ICONS[kind]
  return (
    <Badge variant="outline">
      <Icon aria-hidden />
      {FEEDBACK_KIND_LABELS[kind]}
    </Badge>
  )
}

function StatusBadge({ status }: { status: FeedbackStatus }) {
  const handled = status === 'HANDLED'
  return (
    <Badge variant={handled ? 'outline' : 'warning'}>
      {handled ? <CircleCheck aria-hidden /> : <CircleDot aria-hidden />}
      {FEEDBACK_STATUS_LABELS[status]}
    </Badge>
  )
}

/** Who sent it: the account, the reply address they left, or nobody. */
function Sender({ item }: { item: Feedback }) {
  if (item.sender) return <UserCell user={item.sender} avatar={false} />
  return (
    <div className="min-w-0">
      <span className="block leading-5 text-muted-foreground">Anonymous</span>
      {item.email && (
        <a
          href={`mailto:${item.email}`}
          className="block truncate font-mono text-[0.71875rem] leading-4 text-muted-foreground hover:text-foreground hover:underline"
        >
          {item.email}
        </a>
      )}
    </div>
  )
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)] items-baseline gap-3 py-1.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  )
}

/** The whole message, and the context the form said it was sending. */
function FeedbackDetail({ item }: { item: Feedback }) {
  const size =
    item.viewport_width && item.viewport_height
      ? `${formatNumber(item.viewport_width)} × ${formatNumber(item.viewport_height)}`
      : null
  return (
    <div className="grid gap-5 px-4 py-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:pl-14">
      <p className="min-w-0 text-sm leading-6 wrap-break-word whitespace-pre-line">{item.message}</p>
      <dl className="min-w-0">
        <DetailRow label="Sent">
          <time dateTime={item.created_at} className="tabular-nums">
            {formatDateTime(item.created_at)}
          </time>
        </DetailRow>
        <DetailRow label="Page">
          {item.path ? (
            <Link to={item.path} className="font-mono text-xs break-all hover:underline">
              {item.path}
            </Link>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </DetailRow>
        <DetailRow label="Window">
          {size ? (
            <span className="font-mono text-xs tabular-nums">{size}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </DetailRow>
        <DetailRow label="Browser">
          {item.user_agent ? (
            <span title={item.user_agent}>{describeUserAgent(item.user_agent)}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </DetailRow>
        {item.handled_at && (
          <DetailRow label="Handled">
            <span>
              {formatDateTime(item.handled_at)}
              {item.handled_by ? ` by @${item.handled_by.username}` : ''}
            </span>
          </DetailRow>
        )}
        {item.handled_note && <DetailRow label="Note">{item.handled_note}</DetailRow>}
      </dl>
    </div>
  )
}

export default function AdminFeedbackPage() {
  const { data: me } = useMe()
  const canReview = hasPermission(me, 'feedback:review')

  const [kind, setKind] = useState<FeedbackKind | undefined>(undefined)
  const [status, setStatus] = useState<FeedbackStatus | undefined>(undefined)
  const [page, setPage] = useFilteredPage(`${kind ?? ''}|${status ?? ''}`)
  const query = useAdminFeedback({ kind, status, page, page_size: ADMIN_PAGE_SIZE })

  const handle = useHandleFeedback()
  const [target, setTarget] = useState<Feedback | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const waiting = query.data?.new_count ?? 0

  const columns: AdminColumn<Feedback>[] = [
    { key: 'sender', header: 'From', mobile: 'title', cell: (f) => <Sender item={f} /> },
    { key: 'kind', header: 'Type', mobile: 'aside', cell: (f) => <KindBadge kind={f.kind} /> },
    {
      key: 'message',
      header: 'Message',
      wide: true,
      cell: (f) => <ClampedText text={f.message} className="lg:line-clamp-2 lg:min-w-64" />,
    },
    {
      key: 'page',
      header: 'Page',
      cell: (f) =>
        f.path ? (
          <Link
            to={f.path}
            className="block max-w-40 truncate font-mono text-xs text-muted-foreground hover:text-foreground hover:underline"
            title={f.path}
          >
            {f.path}
          </Link>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    { key: 'status', header: 'Status', mobile: 'aside', cell: (f) => <StatusBadge status={f.status} /> },
    {
      key: 'arrived',
      header: 'Arrived',
      cell: (f) => (
        <span className="block">
          <DateCell iso={f.created_at} />
          <span className="block text-xs leading-4 text-muted-foreground lg:hidden">
            {formatRelative(f.created_at)}
          </span>
        </span>
      ),
    },
  ]

  if (canReview) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      hideHeader: true,
      className: 'text-right',
      mobile: 'actions',
      cell: (f) => (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {f.status === 'HANDLED' ? (
            <Button
              variant="outline"
              size="sm"
              disabled={handle.isPending && handle.variables?.id === f.id}
              onClick={() =>
                handle.mutate(
                  { id: f.id, body: { handled: false } },
                  {
                    onSuccess: () => toast.success('Back in the queue'),
                    onError: (e) => toast.error(errorMessage(e)),
                  },
                )
              }
            >
              <Undo2 aria-hidden /> Reopen
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setTarget(f)
                setDialogOpen(true)
              }}
            >
              <CircleCheck aria-hidden /> Mark handled
            </Button>
          )}
        </div>
      ),
    })
  }

  return (
    <div>
      <PageHeader
        title="Feedback"
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Feedback' }]}
        actions={waiting > 0 ? <Badge variant="warning">{formatNumber(waiting)} waiting</Badge> : undefined}
      />

      <PagedResults
        query={query}
        skeleton="admin-feedback"
        label="Feedback"
        itemLabel="notes"
        errorTitle="Could not load feedback"
        empty={{ icon: MessageSquareText, title: 'No feedback yet' }}
        filtered={!!kind || !!status}
        onClearFilters={() => {
          setKind(undefined)
          setStatus(undefined)
        }}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <>
            <FilterSelect
              id="admin-feedback-kind"
              label="Filter by type"
              value={kind}
              onChange={setKind}
              options={FEEDBACK_KINDS}
              labels={FEEDBACK_KIND_LABELS}
              allLabel="All types"
            />
            <FilterSelect
              id="admin-feedback-status"
              label="Filter by status"
              value={status}
              onChange={setStatus}
              options={FEEDBACK_STATUSES}
              labels={FEEDBACK_STATUS_LABELS}
              allLabel="All statuses"
            />
          </>
        }
      >
        {(items) => (
          <AdminTable
            rows={items}
            columns={columns}
            getKey={(f) => f.id}
            caption="Feedback"
            detail={(f) => <FeedbackDetail item={f} />}
            detailLabel={(f) => `Show the full note from ${formatDateTime(f.created_at)}`}
          />
        )}
      </PagedResults>

      <ReasonDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Mark handled"
        description={
          target ? <span className="text-foreground">“{excerpt(target.message)}”</span> : undefined
        }
        label="Note"
        required={false}
        confirmLabel="Mark handled"
        pending={handle.isPending}
        onConfirm={async (note) => {
          if (!target) return
          try {
            await handle.mutateAsync({ id: target.id, body: { handled: true, note: note || null } })
            toast.success('Marked handled')
          } catch (e) {
            toast.error(errorMessage(e))
            throw e
          }
        }}
      />
    </div>
  )
}
