import { Bot, ChevronRight, ListFilter, ScrollText, Tag } from 'lucide-react'
import { useState } from 'react'

import { MonoValue } from '@/components/common/MonoValue'
import { DataTable, type Column } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { useDebounce } from '@/hooks/useDebounce'
import { useAuditLogs } from '@/lib/api/queries/admin'
import type { AuditLog } from '@/lib/api/types'
import { formatDateTime, formatRelative } from '@/lib/format'

import { FilterBar, PagedResults, SearchField, UserCell } from './admin-shared'
import { ADMIN_PAGE_SIZE, formatJson, humanizeAction, scrollToTop, useFilteredPage } from './admin-utils'

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

function Metadata({ metadata }: { metadata: Record<string, unknown> }) {
  const keys = Object.keys(metadata ?? {})
  if (keys.length === 0) return <span className="text-muted-foreground">—</span>
  return (
    <details className="group max-w-xs text-left">
      <summary className="flex min-h-10 cursor-pointer list-none items-center gap-1 rounded-md text-sm text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-4 shrink-0 transition-transform group-open:rotate-90" aria-hidden />
        <span className="truncate">
          {keys.length === 1 ? '1 field' : `${keys.length} fields`}: {keys.join(', ')}
        </span>
      </summary>
      <pre className="mt-1 max-h-64 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-xs break-all whitespace-pre-wrap">
        {formatJson(metadata)}
      </pre>
    </details>
  )
}

const columns: Column<AuditLog>[] = [
  {
    key: 'time',
    header: 'Time',
    cell: (log) => (
      <time dateTime={log.created_at} className="block whitespace-nowrap tabular-nums">
        {formatDateTime(log.created_at)}
        <span className="block text-xs text-muted-foreground">{formatRelative(log.created_at)}</span>
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
        <Badge variant="muted">
          <Bot aria-hidden /> System
        </Badge>
      ),
  },
  {
    key: 'action',
    header: 'Action',
    cell: (log) => (
      <div className="min-w-0">
        <div className="font-medium">{humanizeAction(log.action)}</div>
        <code className="font-mono text-xs break-all text-muted-foreground">{log.action}</code>
      </div>
    ),
  },
  {
    key: 'entity',
    header: 'Entity',
    cell: (log) => (
      <div className="flex min-w-0 flex-col items-end gap-1 md:items-start">
        <Badge variant="outline">
          <Tag aria-hidden /> {log.entity_type}
        </Badge>
        <MonoValue value={log.entity_id} label={`${log.entity_type} id`} lead={4} tail={4} />
      </div>
    ),
  },
  {
    key: 'metadata',
    header: 'Metadata',
    cell: (log) => <Metadata metadata={log.metadata} />,
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
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Audit logs"
        description="A record of privileged and lifecycle actions: who did what, to which entity, and when. Filters match exact values."
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Audit logs' }]}
      />

      <FilterBar>
        <SearchField
          id="admin-audit-entity-type"
          label="Filter by entity type"
          placeholder="Entity type, e.g. bounty"
          value={entityType}
          onChange={setEntityType}
          maxLength={32}
          icon={ListFilter}
          list="admin-audit-entity-types"
          className="md:max-w-xs"
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
          className="md:max-w-sm"
        />
      </FilterBar>

      <PagedResults
        query={query}
        skeleton="admin-audit-logs"
        label="Audit log entries"
        itemLabel="entries"
        errorTitle="Could not load the audit log"
        empty={{
          icon: ScrollText,
          title: 'No audit entries yet',
          description: 'Recorded actions will appear here.',
        }}
        filtered={!!debouncedEntityType || !!debouncedAction}
        onClearFilters={() => {
          setEntityType('')
          setAction('')
        }}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
      >
        {(items) => (
          <DataTable rows={items} columns={columns} getKey={(log) => log.id} caption="Audit log entries" />
        )}
      </PagedResults>
    </div>
  )
}
