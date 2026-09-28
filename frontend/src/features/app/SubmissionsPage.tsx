import { FileCheck2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { SubmitWorkButton } from '@/components/bounty/SubmitWorkDialog'
import { PaymentStatusBadge, SubmissionStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { DataTable } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useMySubmissions } from '@/lib/api/queries/submissions'
import { SUBMISSION_STATUSES, type SubmissionStatus } from '@/lib/api/types'
import { formatRelative, SUBMISSION_STATUS_LABELS } from '@/lib/format'

const ALL = '__all__'

export default function SubmissionsPage() {
  const [status, setStatus] = useState<SubmissionStatus | null>(null)
  const [page, setPage] = useState(1)
  const query = useMySubmissions({ status: status ?? undefined, page, page_size: 20 })

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="My submissions"
        description="Work you’ve delivered, its review status, and the payout that follows approval."
        actions={
          <Select
            value={status ?? ALL}
            onValueChange={(v) => {
              setStatus(v === ALL ? null : (v as SubmissionStatus))
              setPage(1)
            }}
          >
            <SelectTrigger className="w-52" aria-label="Filter by status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              {SUBMISSION_STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {SUBMISSION_STATUS_LABELS[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      <QueryView
        query={query}
        skeleton="app-submissions"
        isEmpty={(d) => d.items.length === 0}
        empty={{
          icon: FileCheck2,
          title: 'No submissions yet',
          description: 'Once you’re accepted on a bounty, submit your work from its page with “Submit work”.',
          action: (
            <Button asChild variant="outline">
              <Link to="/app/applications">View applications</Link>
            </Button>
          ),
        }}
      >
        {(data) => (
          <>
            <DataTable
              caption="My submissions"
              rows={data.items}
              getKey={(s) => s.id}
              mobileTitle={(s) => (
                <Link to={`/bounties/${s.bounty.slug || s.bounty.id}`} className="hover:underline">
                  {s.bounty.title}
                </Link>
              )}
              columns={[
                {
                  key: 'bounty',
                  header: 'Bounty',
                  mobileHidden: true,
                  cell: (s) => (
                    <Link
                      to={`/bounties/${s.bounty.slug || s.bounty.id}`}
                      className="font-medium hover:underline"
                    >
                      {s.bounty.title}
                    </Link>
                  ),
                },
                {
                  key: 'version',
                  header: 'Version',
                  cell: (s) => <span className="tabular-nums">v{s.version}</span>,
                },
                { key: 'status', header: 'Review', cell: (s) => <SubmissionStatusBadge status={s.status} /> },
                {
                  key: 'payment',
                  header: 'Payout',
                  cell: (s) =>
                    s.payment ? (
                      <PaymentStatusBadge status={s.payment.payment_status} />
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    ),
                },
                {
                  key: 'feedback',
                  header: 'Feedback',
                  cell: (s) => (
                    <span className="line-clamp-2 max-w-xs text-muted-foreground">
                      {s.review_feedback ?? '—'}
                    </span>
                  ),
                },
                {
                  key: 'updated',
                  header: 'Updated',
                  cell: (s) => <span className="text-muted-foreground">{formatRelative(s.updated_at)}</span>,
                },
                {
                  key: 'actions',
                  header: 'Actions',
                  hideLabelOnMobile: true,
                  className: 'text-right',
                  cell: (s) =>
                    s.status === 'REVISION_REQUESTED' ? (
                      <SubmitWorkButton
                        bountyId={s.bounty_id}
                        bountyTitle={s.bounty.title}
                        submission={s}
                        size="sm"
                        variant="outline"
                      />
                    ) : null,
                },
              ]}
            />
            <PaginationBar
              page={data.page}
              pages={data.pages}
              total={data.total}
              pageSize={data.page_size}
              onPageChange={setPage}
              itemLabel="submissions"
            />
          </>
        )}
      </QueryView>
    </div>
  )
}
