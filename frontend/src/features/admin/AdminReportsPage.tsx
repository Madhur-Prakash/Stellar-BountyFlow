import { Flag, Gavel } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { MonoValue } from '@/components/common/MonoValue'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { DataTable, type Column } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorMessage } from '@/lib/api/client'
import { useAdminReports, useResolveReport } from '@/lib/api/queries/admin'
import { useMe } from '@/lib/api/queries/auth'
import { REPORT_STATUSES, type Report, type ReportStatus, type ResolveReportRequest } from '@/lib/api/types'
import { humanize, REPORT_STATUS_LABELS } from '@/lib/format'
import { hasPermission } from '@/lib/permissions'

import {
  ClampedText,
  DateCell,
  FilterBar,
  FilterSelect,
  PagedResults,
  ReportStatusBadge,
  UserCell,
} from './admin-shared'
import {
  ADMIN_PAGE_SIZE,
  bountyPath,
  OPEN_REPORT_STATUSES,
  scrollToTop,
  useFilteredPage,
} from './admin-utils'

type Outcome = ResolveReportRequest['status']

const OUTCOME_LABELS: Record<Outcome, string> = {
  ACTIONED: 'Actioned (action was taken)',
  DISMISSED: 'Dismissed (no action needed)',
}

function ReportTarget({ report }: { report: Report }) {
  const isBounty = report.target_type.toUpperCase() === 'BOUNTY'
  return (
    <div className="flex min-w-0 flex-col items-start gap-1">
      <Badge variant="outline">{humanize(report.target_type)}</Badge>
      {isBounty ? (
        <Link
          to={bountyPath({ id: report.target_id })}
          className="inline-flex min-h-9 items-center gap-1 text-sm font-medium hover:underline"
        >
          View bounty
        </Link>
      ) : (
        <MonoValue
          value={report.target_id}
          label={`reported ${report.target_type.toLowerCase()} id`}
          lead={4}
          tail={4}
        />
      )}
    </div>
  )
}

export default function AdminReportsPage() {
  const { data: me } = useMe()
  const canReview = hasPermission(me, 'report:review')

  const [status, setStatus] = useState<ReportStatus | undefined>(undefined)
  const [page, setPage] = useFilteredPage(status ?? '')
  const query = useAdminReports({ status, page, page_size: ADMIN_PAGE_SIZE })

  const resolve = useResolveReport()
  const [target, setTarget] = useState<Report | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [outcome, setOutcome] = useState<Outcome>('ACTIONED')
  const outcomeId = useId()

  const columns: Column<Report>[] = [
    { key: 'reporter', header: 'Reporter', cell: (r) => <UserCell user={r.reporter} /> },
    { key: 'target', header: 'Target', cell: (r) => <ReportTarget report={r} /> },
    { key: 'reason', header: 'Reason', cell: (r) => <ClampedText text={r.reason} /> },
    { key: 'status', header: 'Status', cell: (r) => <ReportStatusBadge status={r.status} /> },
    { key: 'created', header: 'Reported', cell: (r) => <DateCell iso={r.created_at} /> },
    {
      key: 'resolution',
      header: 'Resolution note',
      cell: (r) => <ClampedText text={r.resolution_note} className="text-muted-foreground" />,
    },
  ]

  if (canReview) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      hideLabelOnMobile: true,
      cell: (r) =>
        OPEN_REPORT_STATUSES.has(r.status) ? (
          <Button
            variant="outline"
            disabled={resolve.isPending && resolve.variables?.id === r.id}
            aria-label={`Resolve report from @${r.reporter.username}`}
            onClick={() => {
              setTarget(r)
              setOutcome('ACTIONED')
              setDialogOpen(true)
            }}
          >
            <Gavel aria-hidden /> Resolve
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">Closed</span>
        ),
    })
  }

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Reports"
        description={
          canReview
            ? 'Reports submitted by the community. Review the target, then action or dismiss each report with a note.'
            : 'Reports submitted by the community.'
        }
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Reports' }]}
      />

      <FilterBar>
        <FilterSelect
          id="admin-reports-status"
          label="Filter by status"
          value={status}
          onChange={setStatus}
          options={REPORT_STATUSES}
          labels={REPORT_STATUS_LABELS}
          allLabel="All statuses"
        />
      </FilterBar>

      <PagedResults
        query={query}
        skeleton="admin-reports"
        label="Reports"
        itemLabel="reports"
        errorTitle="Could not load reports"
        empty={{
          icon: Flag,
          title: 'No reports',
          description: 'Nobody has reported a bounty, user, or submission yet.',
        }}
        filtered={!!status}
        onClearFilters={() => setStatus(undefined)}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
      >
        {(items) => (
          <DataTable rows={items} columns={columns} getKey={(r) => r.id} caption="Community reports" />
        )}
      </PagedResults>

      <ReasonDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Resolve report"
        description={
          target ? (
            <>
              Reported by @{target.reporter.username}:{' '}
              <span className="text-foreground">“{target.reason}”</span>
            </>
          ) : undefined
        }
        label="Resolution note"
        confirmLabel="Resolve report"
        pending={resolve.isPending}
        onConfirm={async (note) => {
          if (!target) return
          try {
            await resolve.mutateAsync({ id: target.id, body: { status: outcome, note } })
            toast.success(outcome === 'ACTIONED' ? 'Report marked as actioned.' : 'Report dismissed.')
          } catch (e) {
            toast.error(errorMessage(e))
            throw e
          }
        }}
      >
        <div className="space-y-2">
          <Label htmlFor={outcomeId}>Outcome</Label>
          <Select value={outcome} onValueChange={(v) => setOutcome(v as Outcome)}>
            <SelectTrigger id={outcomeId} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(OUTCOME_LABELS) as Outcome[]).map((o) => (
                <SelectItem key={o} value={o}>
                  {OUTCOME_LABELS[o]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </ReasonDialog>
    </div>
  )
}
