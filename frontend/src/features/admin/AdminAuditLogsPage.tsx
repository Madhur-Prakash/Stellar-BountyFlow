import { ArrowRight, Bot, ListFilter, ScrollText } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { MonoValue } from '@/components/common/MonoValue'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { useDebounce } from '@/hooks/useDebounce'
import { useAuditLogs } from '@/lib/api/queries/admin'
import type { AuditLog } from '@/lib/api/types'
import { formatDateTime, formatRelative, humanize } from '@/lib/format'

import { AdminTable, PagedResults, SearchField, UserCell, type AdminColumn } from './admin-shared'
import {
  ADMIN_PAGE_SIZE,
  formatJson,
  humanizeAction,
  isIsoDateTime,
  isRecord,
  scrollToTop,
  useFilteredPage,
} from './admin-utils'

/** Entity types written by the API today; offered as suggestions only (any value can be typed). */
const ENTITY_TYPE_SUGGESTIONS = [
  'application',
  'bounty',
  'dispute',
  'payment',
  'report',
  'submission',
  'transaction',
  'user',
  'wallet',
]

type Change = { from: unknown; to: unknown }

/** A state change recorded as `{ from, to }`, if the entry has one. */
function changeOf(metadata: Record<string, unknown>): Change | null {
  return 'from' in metadata && 'to' in metadata ? { from: metadata.from, to: metadata.to } : null
}

function scalar(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return isIsoDateTime(value) ? formatDateTime(value) : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return formatJson(value)
}

function ChangeValue({ value, muted = false }: { value: unknown; muted?: boolean }) {
  return (
    <code
      className={
        muted
          ? 'rounded border bg-card px-1.5 py-0.5 font-mono text-xs text-muted-foreground'
          : 'rounded border bg-card px-1.5 py-0.5 font-mono text-xs text-foreground'
      }
    >
      {scalar(value)}
    </code>
  )
}

function ChangeLine({ change }: { change: Change }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <ChangeValue value={change.from} muted />
      <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
      <span className="sr-only">to</span>
      <ChangeValue value={change.to} />
    </span>
  )
}

/** One-line summary for the table: the state change, or the recorded field names. */
function MetadataSummary({ metadata }: { metadata: Record<string, unknown> }) {
  const change = changeOf(metadata)
  if (change) return <ChangeLine change={change} />
  const keys = Object.keys(metadata)
  if (keys.length === 0) return <span className="text-muted-foreground">—</span>
  return (
    <span className="block max-w-64 truncate text-muted-foreground" title={keys.join(', ')}>
      {keys.map(humanize).join(', ')}
    </span>
  )
}

function FieldValue({ value }: { value: unknown }) {
  if (Array.isArray(value) && value.every((v) => typeof v === 'string')) {
    return (
      <span className="flex flex-wrap gap-1">
        {value.map((v) => (
          <code key={v} className="rounded border bg-card px-1.5 py-0.5 font-mono text-xs">
            {v}
          </code>
        ))}
      </span>
    )
  }
  if (isRecord(value) || Array.isArray(value)) {
    return <pre className="font-mono text-xs break-all whitespace-pre-wrap">{formatJson(value)}</pre>
  }
  return <span className="wrap-break-word whitespace-pre-line">{scalar(value)}</span>
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)] items-baseline gap-3 py-1.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  )
}

/** Expanded entry: every recorded field, the state change, and the raw metadata as JSON. */
function AuditDetail({ log }: { log: AuditLog }) {
  const metadata = isRecord(log.metadata) ? log.metadata : {}
  const change = changeOf(metadata)
  const fields = Object.entries(metadata).filter(([k]) => !(change && (k === 'from' || k === 'to')))
  return (
    <div className="grid gap-5 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:pl-14">
      <dl className="min-w-0">
        <DetailRow label="Time">
          <time dateTime={log.created_at} className="tabular-nums">
            {formatDateTime(log.created_at)}
          </time>
        </DetailRow>
        <DetailRow label="Actor">
          {log.actor ? `${log.actor.display_name || log.actor.username} (@${log.actor.username})` : 'System'}
        </DetailRow>
        <DetailRow label="Action">
          <code className="font-mono text-xs">{log.action}</code>
        </DetailRow>
        <DetailRow label={humanize(log.entity_type)}>
          <MonoValue value={log.entity_id} label={`${log.entity_type} id`} lead={8} tail={8} />
        </DetailRow>
        {change && (
          <DetailRow label="Change">
            <ChangeLine change={change} />
          </DetailRow>
        )}
        {fields.map(([key, value]) => (
          <DetailRow key={key} label={humanize(key)}>
            <FieldValue value={value} />
          </DetailRow>
        ))}
        <DetailRow label="Entry">
          <MonoValue value={log.id} label="audit entry id" lead={8} tail={8} />
        </DetailRow>
      </dl>
      <div className="min-w-0">
        <div className="mb-1.5 text-xs text-muted-foreground">Metadata</div>
        <pre className="max-h-72 overflow-auto rounded-md border bg-card p-3 font-mono text-xs leading-5 break-all whitespace-pre-wrap">
          {formatJson(metadata)}
        </pre>
      </div>
    </div>
  )
}

const columns: AdminColumn<AuditLog>[] = [
  {
    key: 'time',
    header: 'Time',
    mobile: 'aside',
    cell: (log) => (
      <time
        dateTime={log.created_at}
        title={formatDateTime(log.created_at)}
        className="block whitespace-nowrap"
      >
        <span className="hidden leading-5 tabular-nums lg:block">{formatDateTime(log.created_at)}</span>
        <span className="block text-xs leading-4 text-muted-foreground">
          {formatRelative(log.created_at)}
        </span>
      </time>
    ),
  },
  {
    key: 'actor',
    header: 'Actor',
    cell: (log) =>
      log.actor ? (
        <UserCell user={log.actor} />
      ) : (
        <Badge variant="outline">
          <Bot aria-hidden /> System
        </Badge>
      ),
  },
  {
    key: 'action',
    header: 'Action',
    mobile: 'title',
    cell: (log) => (
      <div className="min-w-0">
        <div className="leading-5 font-medium">{humanizeAction(log.action)}</div>
        <code className="block font-mono text-xs leading-4 break-all text-muted-foreground">
          {log.action}
        </code>
      </div>
    ),
  },
  {
    key: 'entity',
    header: 'Entity',
    cell: (log) => (
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 lg:flex-nowrap">
        <Badge variant="outline">{log.entity_type}</Badge>
        <MonoValue value={log.entity_id} label={`${log.entity_type} id`} lead={4} tail={4} />
      </span>
    ),
  },
  {
    key: 'metadata',
    header: 'Metadata',
    wide: true,
    cell: (log) => <MetadataSummary metadata={isRecord(log.metadata) ? log.metadata : {}} />,
  },
]

export default function AdminAuditLogsPage() {
  const [entityType, setEntityType] = useState('')
  const [action, setAction] = useState('')
  const debouncedEntityType = useDebounce(entityType.trim(), 300)
  const debouncedAction = useDebounce(action.trim(), 300)
  const [page, setPage] = useFilteredPage(`${debouncedEntityType}|${debouncedAction}`)
  const query = useAuditLogs({
    entity_type: debouncedEntityType || undefined,
    action: debouncedAction || undefined,
    page,
    page_size: ADMIN_PAGE_SIZE,
  })

  return (
    <div>
      <PageHeader
        title="Audit logs"
        description="Privileged and lifecycle actions. Filters match exact values."
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Audit logs' }]}
      />

      <PagedResults
        query={query}
        skeleton="admin-audit-logs"
        label="Audit log entries"
        itemLabel="entries"
        errorTitle="Could not load the audit log"
        empty={{ icon: ScrollText, title: 'No audit entries yet' }}
        filtered={!!debouncedEntityType || !!debouncedAction}
        onClearFilters={() => {
          setEntityType('')
          setAction('')
        }}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <>
            <SearchField
              id="admin-audit-entity-type"
              label="Filter by entity type"
              placeholder="Entity type, e.g. bounty"
              value={entityType}
              onChange={setEntityType}
              maxLength={32}
              icon={ListFilter}
              list="admin-audit-entity-types"
              className="sm:w-64"
            />
            <datalist id="admin-audit-entity-types">
              {ENTITY_TYPE_SUGGESTIONS.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
            <SearchField
              id="admin-audit-action"
              label="Filter by action"
              placeholder="Action, e.g. dispute.resolved"
              value={action}
              onChange={setAction}
              maxLength={64}
              icon={ListFilter}
            />
          </>
        }
      >
        {(items) => (
          <AdminTable
            rows={items}
            columns={columns}
            getKey={(log) => log.id}
            caption="Audit log entries"
            detail={(log) => <AuditDetail log={log} />}
            detailLabel={(log) =>
              `Show details for ${humanizeAction(log.action)} at ${formatDateTime(log.created_at)}`
            }
          />
        )}
      </PagedResults>
    </div>
  )
}
