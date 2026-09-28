import { GitPullRequest, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ApplicationStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Button } from '@/components/ui/button'
import { Card, CardFooter } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { errorMessage } from '@/lib/api/client'
import { useMyApplications, useWithdrawApplication } from '@/lib/api/queries/applications'
import type { Application, ApplicationStatus } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS, formatDateTime, formatRelative } from '@/lib/format'

import { CardQuery, CardToolbar, ResponsiveTable } from './workspace-ui'

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

function BountyLink({ app }: { app: Application }) {
  return (
    <Link
      to={`/bounties/${app.bounty.slug || app.bounty.id}`}
      className="line-clamp-2 font-medium hover:underline"
    >
      {app.bounty.title}
    </Link>
  )
}

function Sent({ app }: { app: Application }) {
  return (
    <time dateTime={app.created_at} title={formatDateTime(app.created_at)} className="tabular-nums">
      {formatRelative(app.created_at)}
    </time>
  )
}

export default function ApplicationsPage() {
  const [status, setStatus] = useState<ApplicationStatus | 'ALL'>('ALL')
  const [page, setPage] = useState(1)
  const query = useMyApplications({ status: status === 'ALL' ? undefined : status, page, page_size: 20 })

  return (
    <div>
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
      >
        <Card className="gap-0 py-0">
          <CardToolbar>
            <TabsList className="h-9 max-w-full scrollbar-thin justify-start overflow-x-auto">
              {FILTERS.map((f) => (
                <TabsTrigger key={f.value} value={f.value} className="flex-none px-3">
                  {f.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </CardToolbar>

          <TabsContent value={status}>
            <CardQuery
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
                  <ResponsiveTable
                    caption="My applications"
                    rows={data.items}
                    getKey={(a) => a.id}
                    columns={[
                      {
                        key: 'bounty',
                        header: 'Bounty',
                        className: 'min-w-64 whitespace-normal',
                        cell: (a) => <BountyLink app={a} />,
                      },
                      {
                        key: 'bstatus',
                        header: 'Bounty status',
                        className: 'text-muted-foreground',
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
                        className: 'text-muted-foreground',
                        cell: (a) => <Sent app={a} />,
                      },
                      {
                        key: 'actions',
                        header: <span className="sr-only">Actions</span>,
                        className: 'w-px text-right',
                        cell: (a) => <WithdrawButton app={a} />,
                      },
                    ]}
                    renderMobile={(a) => (
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1.5">
                          <BountyLink app={a} />
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                            <ApplicationStatusBadge status={a.status} />
                            <span>Bounty {BOUNTY_STATUS_LABELS[a.bounty.status].toLowerCase()}</span>
                            <Sent app={a} />
                          </div>
                        </div>
                        <div className="-mr-2 shrink-0">
                          <WithdrawButton app={a} />
                        </div>
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
                      itemLabel="applications"
                      className="w-full pt-0"
                    />
                  </CardFooter>
                </>
              )}
            </CardQuery>
          </TabsContent>
        </Card>
      </Tabs>
    </div>
  )
}
