import { GitPullRequest, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ApplicationStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { DataTable } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { errorMessage } from '@/lib/api/client'
import { useMyApplications, useWithdrawApplication } from '@/lib/api/queries/applications'
import type { Application, ApplicationStatus } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS, formatRelative } from '@/lib/format'

const FILTERS: { value: ApplicationStatus | 'ALL'; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'ACCEPTED', label: 'Accepted' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'WITHDRAWN', label: 'Withdrawn' },
]

function WithdrawButton({ app }: { app: Application }) {
  const withdraw = useWithdrawApplication()
  if (app.status !== 'PENDING' && app.status !== 'ACCEPTED') return null
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={withdraw.isPending}
      onClick={() =>
        withdraw.mutate(app.id, {
          onSuccess: () => toast.success('Application withdrawn'),
          onError: (e) => toast.error(errorMessage(e)),
        })
      }
    >
      Withdraw
    </Button>
  )
}

export default function ApplicationsPage() {
  const [status, setStatus] = useState<ApplicationStatus | 'ALL'>('ALL')
  const [page, setPage] = useState(1)
  const query = useMyApplications({ status: status === 'ALL' ? undefined : status, page, page_size: 20 })

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="My applications"
        description="Bounties you’ve applied to and where each application stands."
        actions={
          <Button asChild variant="outline">
            <Link to="/bounties">
              <Search /> Find work
            </Link>
          </Button>
        }
      />
      <Tabs
        value={status}
        onValueChange={(v) => {
          setStatus(v as ApplicationStatus | 'ALL')
          setPage(1)
        }}
        className="mb-4"
      >
        <TabsList className="max-w-full overflow-x-auto">
          {FILTERS.map((f) => (
            <TabsTrigger key={f.value} value={f.value}>
              {f.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value={status}>
          <QueryView
            query={query}
            skeleton="app-applications"
            isEmpty={(d) => d.items.length === 0}
            empty={{
              icon: GitPullRequest,
              title: status === 'ALL' ? 'No applications yet' : 'Nothing in this state',
              description: 'Browse the marketplace and apply to bounties that match your skills.',
              action: (
                <Button asChild>
                  <Link to="/bounties">Browse bounties</Link>
                </Button>
              ),
            }}
          >
            {(data) => (
              <>
                <DataTable
                  caption="My applications"
                  rows={data.items}
                  getKey={(a) => a.id}
                  mobileTitle={(a) => (
                    <Link to={`/bounties/${a.bounty.slug || a.bounty.id}`} className="hover:underline">
                      {a.bounty.title}
                    </Link>
                  )}
                  columns={[
                    {
                      key: 'bounty',
                      header: 'Bounty',
                      mobileHidden: true,
                      cell: (a) => (
                        <Link
                          to={`/bounties/${a.bounty.slug || a.bounty.id}`}
                          className="font-medium hover:underline"
                        >
                          {a.bounty.title}
                        </Link>
                      ),
                    },
                    {
                      key: 'bstatus',
                      header: 'Bounty status',
                      cell: (a) => BOUNTY_STATUS_LABELS[a.bounty.status],
                    },
                    {
                      key: 'status',
                      header: 'Application',
                      cell: (a) => <ApplicationStatusBadge status={a.status} />,
                    },
                    {
                      key: 'sent',
                      header: 'Sent',
                      cell: (a) => (
                        <span className="text-muted-foreground">{formatRelative(a.created_at)}</span>
                      ),
                    },
                    {
                      key: 'actions',
                      header: 'Actions',
                      hideLabelOnMobile: true,
                      className: 'text-right',
                      cell: (a) => <WithdrawButton app={a} />,
                    },
                  ]}
                />
                <PaginationBar
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  pageSize={data.page_size}
                  onPageChange={setPage}
                  itemLabel="applications"
                />
              </>
            )}
          </QueryView>
        </TabsContent>
      </Tabs>
    </div>
  )
}
