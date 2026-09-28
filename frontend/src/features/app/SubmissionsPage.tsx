import { FileCheck2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { SubmitWorkButton } from '@/components/bounty/SubmitWorkDialog'
import { PaymentStatusBadge, SubmissionStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Button } from '@/components/ui/button'
import { Card, CardFooter } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useMySubmissions } from '@/lib/api/queries/submissions'
import { SUBMISSION_STATUSES, type Submission, type SubmissionStatus } from '@/lib/api/types'
import { formatDateTime, formatRelative, SUBMISSION_STATUS_LABELS } from '@/lib/format'

import { CardQuery, CardToolbar, ResponsiveTable } from './workspace-ui'

const ALL = '__all__'

function BountyLink({ s }: { s: Submission }) {
  return (
    <Link
      to={`/bounties/${s.bounty.slug || s.bounty.id}`}
      className="line-clamp-2 font-medium hover:underline"
    >
      {s.bounty.title}
    </Link>
  )
}

function Updated({ s }: { s: Submission }) {
  return (
    <time dateTime={s.updated_at} title={formatDateTime(s.updated_at)} className="tabular-nums">
      {formatRelative(s.updated_at)}
    </time>
  )
}

function Revise({ s }: { s: Submission }) {
  if (s.status !== 'REVISION_REQUESTED') return null
  return (
    <SubmitWorkButton
      bountyId={s.bounty_id}
      bountyTitle={s.bounty.title}
      submission={s}
      size="sm"
      variant="outline"
    />
  )
}

export default function SubmissionsPage() {
  const [status, setStatus] = useState<SubmissionStatus | null>(null)
  const [page, setPage] = useState(1)
  const query = useMySubmissions({ status: status ?? undefined, page, page_size: 20 })

  return (
    <div>
      <PageHeader
        title="My submissions"
        description="Work you’ve delivered, with its review and payout status."
      />
      <Card className="gap-0 py-0">
        <CardToolbar>
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
        </CardToolbar>

        <CardQuery
          query={query}
          skeleton="app-submissions"
          isEmpty={(d) => d.items.length === 0}
          empty={{
            icon: FileCheck2,
            title: status ? 'Nothing in this state' : 'No submissions yet',
            description: 'When you’re accepted on a bounty, send your work from its page with “Submit work”.',
            action: (
              <Button asChild variant="outline">
                <Link to="/app/applications">View applications</Link>
              </Button>
            ),
          }}
        >
          {(data) => (
            <>
              <ResponsiveTable
                caption="My submissions"
                rows={data.items}
                getKey={(s) => s.id}
                stackBelow="lg"
                columns={[
                  {
                    key: 'bounty',
                    header: 'Bounty',
                    className: 'min-w-56 whitespace-normal',
                    cell: (s) => <BountyLink s={s} />,
                  },
                  {
                    key: 'version',
                    header: 'Version',
                    cell: (s) => <span className="tabular-nums">v{s.version}</span>,
                  },
                  {
                    key: 'status',
                    header: 'Review',
                    cell: (s) => <SubmissionStatusBadge status={s.status} />,
                  },
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
                    className: 'min-w-48 whitespace-normal',
                    cell: (s) => (
                      <span className="line-clamp-2 max-w-xs text-muted-foreground">
                        {s.review_feedback ?? '—'}
                      </span>
                    ),
                  },
                  {
                    key: 'updated',
                    header: 'Updated',
                    className: 'text-muted-foreground',
                    cell: (s) => <Updated s={s} />,
                  },
                  {
                    key: 'actions',
                    header: <span className="sr-only">Actions</span>,
                    className: 'w-px text-right',
                    cell: (s) => <Revise s={s} />,
                  },
                ]}
                renderMobile={(s) => (
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-3">
                      <BountyLink s={s} />
                      <span className="shrink-0 text-sm text-muted-foreground tabular-nums">
                        v{s.version}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted-foreground">
                      <SubmissionStatusBadge status={s.status} />
                      {s.payment && <PaymentStatusBadge status={s.payment.payment_status} />}
                      <Updated s={s} />
                    </div>
                    {s.review_feedback && (
                      <p className="line-clamp-3 text-sm text-muted-foreground">{s.review_feedback}</p>
                    )}
                    {s.status === 'REVISION_REQUESTED' && (
                      <div className="pt-1">
                        <Revise s={s} />
                      </div>
                    )}
                  </div>
                )}
              />
              <CardFooter className="px-4 py-3 sm:px-5">
                <PaginationBar
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  pageSize={data.page_size}
                  onPageChange={setPage}
                  itemLabel="submissions"
                  className="w-full pt-0"
                />
              </CardFooter>
            </>
          )}
        </CardQuery>
      </Card>
    </div>
  )
}
