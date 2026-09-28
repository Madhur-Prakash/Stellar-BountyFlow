import { Flag, Gavel } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { MonoValue } from '@/components/common/MonoValue'
import { ReasonDialog } from '@/components/common/ReasonDialog'
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
  AdminTable,
  ClampedText,
  DateCell,
  FilterSelect,
  PagedResults,
  ReportStatusBadge,
  UserCell,
  type AdminColumn,
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
  ACTIONED: 'Actioned',
  DISMISSED: 'Dismissed',
}

function ReportTarget({ report }: { report: Report }) {
  const isBounty = report.target_type.toUpperCase() === 'BOUNTY'
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Badge variant="outline">{humanize(report.target_type)}</Badge>
      {isBounty ? (
        <Link to={bountyPath({ id: report.target_id })} className="text-sm font-medium hover:underline">
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

  const columns: AdminColumn<Report>[] = [
    {
      key: 'reporter',
      header: 'Reporter',
      mobile: 'title',
      cell: (r) => <UserCell user={r.reporter} avatar={false} />,
    },
    { key: 'target', header: 'Target', cell: (r) => <ReportTarget report={r} /> },
    {
      key: 'reason',
      header: 'Reason',
      wide: true,
      cell: (r) => <ClampedText text={r.reason} className="lg:line-clamp-2 lg:min-w-48" />,
    },
    {
      key: 'status',
      header: 'Status',
      mobile: 'aside',
      cell: (r) => (
        <div className="min-w-0">
          <ReportStatusBadge status={r.status} />
          {r.resolution_note && (
            <p
              className="mt-0.5 hidden max-w-36 truncate text-xs leading-4 text-muted-foreground lg:block"
              title={r.resolution_note}
            >
              {r.resolution_note}
            </p>
          )}
        </div>
      ),
    },
    { key: 'created', header: 'Reported', cell: (r) => <DateCell iso={r.created_at} /> },
    {
      key: 'resolution',
      header: 'Resolution note',
      wide: true,
      desktopHidden: true,
      cell: (r) => <ClampedText text={r.resolution_note} className="text-muted-foreground" />,
    },
  ]

  if (canReview) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      hideHeader: true,
      className: 'text-right',
      mobile: 'actions',
      cell: (r) =>
        OPEN_REPORT_STATUSES.has(r.status) ? (
          <Button
            variant="outline"
            size="sm"
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
    <div>
      <PageHeader title="Reports" breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Reports' }]} />

      <PagedResults
        query={query}
        skeleton="admin-reports"
        label="Reports"
        itemLabel="reports"
        errorTitle="Could not load reports"
        empty={{ icon: Flag, title: 'No reports' }}
        filtered={!!status}
        onClearFilters={() => setStatus(undefined)}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <FilterSelect
            id="admin-reports-status"
            label="Filter by status"
            value={status}
            onChange={setStatus}
            options={REPORT_STATUSES}
            labels={REPORT_STATUS_LABELS}
            allLabel="All statuses"
          />
        }
      >
        {(items) => (
          <AdminTable rows={items} columns={columns} getKey={(r) => r.id} caption="Community reports" />
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
