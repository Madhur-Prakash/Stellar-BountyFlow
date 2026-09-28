import { BriefcaseBusiness, PlusCircle } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { BountyStatusBadge } from '@/components/bounty/BountyStatusBadge'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { DataTable } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMyBounties } from '@/lib/api/queries/bounties'
import { BOUNTY_STATUSES, type BountyStatus } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS, formatRelative } from '@/lib/format'
import { formatAmount } from '@/lib/money'

const ALL = '__all__'

export default function MyBountiesPage() {
  const [role, setRole] = useState<'requester' | 'contributor'>('requester')
  const [status, setStatus] = useState<BountyStatus | null>(null)
  const [page, setPage] = useState(1)
  const query = useMyBounties({ role, status: status ?? undefined, page, page_size: 20 })

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="My bounties"
        description="Bounties you’ve posted, and bounties you’re working on."
        actions={
          <Button asChild>
            <Link to="/app/bounties/create">
              <PlusCircle /> Post a bounty
            </Link>
          </Button>
        }
      />
      <Tabs
        value={role}
        onValueChange={(v) => {
          setRole(v as 'requester' | 'contributor')
          setPage(1)
        }}
      >
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <TabsList>
            <TabsTrigger value="requester">Posted by me</TabsTrigger>
            <TabsTrigger value="contributor">Working on</TabsTrigger>
          </TabsList>

          <Select
            value={status ?? ALL}
            onValueChange={(v) => {
              setStatus(v === ALL ? null : (v as BountyStatus))
              setPage(1)
            }}
          >
            <SelectTrigger className="w-full sm:w-52" aria-label="Filter by status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              {BOUNTY_STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {BOUNTY_STATUS_LABELS[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <TabsContent value={role}>
          <QueryView
            query={query}
            skeleton="app-my-bounties"
            isEmpty={(d) => d.items.length === 0}
            empty={{
              icon: BriefcaseBusiness,
              title:
                role === 'requester'
                  ? 'You haven’t posted a bounty yet'
                  : 'You’re not assigned to any bounties yet',
              description:
                role === 'requester'
                  ? 'Describe the work, set a reward, and fund the escrow.'
                  : 'Apply to bounties in the marketplace to get started.',
              action:
                role === 'requester' ? (
                  <Button asChild>
                    <Link to="/app/bounties/create">Post a bounty</Link>
                  </Button>
                ) : (
                  <Button asChild variant="outline">
                    <Link to="/bounties">Browse bounties</Link>
                  </Button>
                ),
            }}
          >
            {(data) => (
              <>
                <DataTable
                  caption="My bounties"
                  rows={data.items}
                  getKey={(b) => b.id}
                  mobileTitle={(b) => (
                    <Link
                      to={role === 'requester' ? `/app/bounties/${b.id}` : `/bounties/${b.slug || b.id}`}
                      className="hover:underline"
                    >
                      {b.title}
                    </Link>
                  )}
                  columns={[
                    {
                      key: 'title',
                      header: 'Bounty',
                      mobileHidden: true,
                      cell: (b) => (
                        <Link
                          to={role === 'requester' ? `/app/bounties/${b.id}` : `/bounties/${b.slug || b.id}`}
                          className="font-medium hover:underline"
                        >
                          {b.title}
                        </Link>
                      ),
                    },
                    { key: 'status', header: 'Status', cell: (b) => <BountyStatusBadge status={b.status} /> },
                    {
                      key: 'funding',
                      header: 'Funding',
                      cell: (b) => <FundingStatusBadge status={b.funding_status} bountyStatus={b.status} />,
                    },
                    {
                      key: 'reward',
                      header: 'Reward',
                      className: 'text-right',
                      cell: (b) => (
                        <span className="tabular-nums">
                          {formatAmount(b.reward_amount)}{' '}
                          <span className="text-muted-foreground">{b.reward_asset.code}</span>
                        </span>
                      ),
                    },
                    {
                      key: 'apps',
                      header: 'Applicants',
                      className: 'text-right',
                      cell: (b) => <span className="tabular-nums">{b.applications_count}</span>,
                    },
                    {
                      key: 'created',
                      header: 'Created',
                      cell: (b) => (
                        <span className="text-muted-foreground">{formatRelative(b.created_at)}</span>
                      ),
                    },
                  ]}
                />
                <PaginationBar
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  pageSize={data.page_size}
                  onPageChange={setPage}
                  itemLabel="bounties"
                />
              </>
            )}
          </QueryView>
        </TabsContent>
      </Tabs>
    </div>
  )
}
