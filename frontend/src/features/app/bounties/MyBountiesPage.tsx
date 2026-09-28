import {
  BriefcaseBusiness,
  ExternalLink,
  FileCheck2,
  GitPullRequest,
  MoreHorizontal,
  PencilLine,
  PlusCircle,
  Settings2,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { BountyStatusBadge } from '@/components/bounty/BountyStatusBadge'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { MetaList } from '@/components/bounty/MetaList'
import { bountyHref } from '@/components/bounty/bounty-display'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMyBounties } from '@/lib/api/queries/bounties'
import { BOUNTY_STATUSES, type BountyStatus, type BountySummary } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS, formatDate, formatNumber, formatRelative } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

const ALL = '__all__'
type Role = 'requester' | 'contributor'

const canEdit = (b: BountySummary) =>
  b.status === 'DRAFT' || (b.status === 'OPEN' && b.funding_status === 'UNFUNDED')

const primaryHref = (b: BountySummary, role: Role) =>
  role === 'requester' ? `/app/bounties/${b.id}` : bountyHref(b)

function Reward({ b }: { b: BountySummary }) {
  return (
    <span className="whitespace-nowrap">
      <span className="amount">{formatAmount(b.reward_amount)}</span>{' '}
      <span className="text-xs text-muted-foreground">{b.reward_asset.code}</span>
    </span>
  )
}

function Deadline({ iso }: { iso: string | null }) {
  return <span className="text-muted-foreground">{iso ? formatDate(iso) : 'No deadline'}</span>
}

function RowActions({ b, role }: { b: BountySummary; role: Role }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Actions for ${b.title}`}
          className="text-muted-foreground"
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {role === 'requester' ? (
          <>
            <DropdownMenuItem asChild>
              <Link to={`/app/bounties/${b.id}`}>
                <Settings2 /> Manage
              </Link>
            </DropdownMenuItem>
            {canEdit(b) && (
              <DropdownMenuItem asChild>
                <Link to={`/app/bounties/${b.id}/edit`}>
                  <PencilLine /> Edit
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem asChild>
              <Link to={`/app/bounties/${b.id}/applications`}>
                <GitPullRequest /> Applications
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to={`/app/bounties/${b.id}/submissions`}>
                <FileCheck2 /> Submissions
              </Link>
            </DropdownMenuItem>
            {b.status !== 'DRAFT' && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link to={bountyHref(b)}>
                    <ExternalLink /> Public page
                  </Link>
                </DropdownMenuItem>
              </>
            )}
          </>
        ) : (
          <>
            <DropdownMenuItem asChild>
              <Link to={bountyHref(b)}>
                <ExternalLink /> View bounty
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to="/app/submissions">
                <FileCheck2 /> My submissions
              </Link>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function BountiesTable({ rows, role }: { rows: BountySummary[]; role: Role }) {
  return (
    <>
      <div className="hidden lg:block">
        <Table>
          <caption className="sr-only">My bounties</caption>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-5">Bounty</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Funding</TableHead>
              <TableHead className="text-right">Reward</TableHead>
              <TableHead className="hidden text-right xl:table-cell">Applicants</TableHead>
              <TableHead>Deadline</TableHead>
              <TableHead className="w-12 pr-5">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((b) => (
              <TableRow key={b.id}>
                <TableCell className="max-w-md min-w-60 pl-5 whitespace-normal">
                  <Link to={primaryHref(b, role)} className="line-clamp-1 font-medium hover:underline">
                    {b.title}
                  </Link>
                  <div className="text-xs text-muted-foreground">Created {formatRelative(b.created_at)}</div>
                </TableCell>
                <TableCell>
                  <BountyStatusBadge status={b.status} />
                </TableCell>
                <TableCell>
                  <FundingStatusBadge status={b.funding_status} bountyStatus={b.status} />
                </TableCell>
                <TableCell className="text-right">
                  <Reward b={b} />
                </TableCell>
                <TableCell className="hidden text-right tabular-nums xl:table-cell">
                  {formatNumber(b.applications_count)}
                </TableCell>
                <TableCell>
                  <Deadline iso={b.application_deadline} />
                </TableCell>
                <TableCell className="pr-5 text-right">
                  <RowActions b={b} role={role} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="divide-y lg:hidden" aria-label="My bounties">
        {rows.map((b) => (
          <li key={b.id} className="space-y-2 px-4 py-3.5">
            <div className="flex items-start justify-between gap-2">
              <Link to={primaryHref(b, role)} className="min-w-0 pt-1 text-sm font-medium hover:underline">
                {b.title}
              </Link>
              <RowActions b={b} role={role} />
            </div>
            <div className="flex flex-wrap gap-1.5">
              <BountyStatusBadge status={b.status} />
              <FundingStatusBadge status={b.funding_status} bountyStatus={b.status} />
            </div>
            <MetaList>
              <span className="text-foreground">
                <Reward b={b} />
              </span>
              <span className="tabular-nums">
                {b.applications_count} applicant{b.applications_count === 1 ? '' : 's'}
              </span>
              <span>
                {b.application_deadline ? `Closes ${formatDate(b.application_deadline)}` : 'No deadline'}
              </span>
            </MetaList>
          </li>
        ))}
      </ul>
    </>
  )
}

export default function MyBountiesPage() {
  const [role, setRole] = useState<Role>('requester')
  const [status, setStatus] = useState<BountyStatus | null>(null)
  const [page, setPage] = useState(1)
  const query = useMyBounties({ role, status: status ?? undefined, page, page_size: 20 })
  const showingRows = !query.isError && !!query.data && query.data.items.length > 0

  return (
    <div>
      <PageHeader
        title="My bounties"
        actions={
          <Button asChild>
            <Link to="/app/bounties/create">
              <PlusCircle /> Post a bounty
            </Link>
          </Button>
        }
      />
      <Card className="gap-0 py-0">
        <Tabs
          value={role}
          onValueChange={(v) => {
            setRole(v as Role)
            setPage(1)
          }}
          className="gap-0"
        >
          <div className="flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <TabsList>
              <TabsTrigger value="requester" className="px-3">
                Posted by me
              </TabsTrigger>
              <TabsTrigger value="contributor" className="px-3">
                Working on
              </TabsTrigger>
            </TabsList>

            <Select
              value={status ?? ALL}
              onValueChange={(v) => {
                setStatus(v === ALL ? null : (v as BountyStatus))
                setPage(1)
              }}
            >
              <SelectTrigger className="w-full sm:w-48" aria-label="Filter by status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end">
                <SelectItem value={ALL}>All statuses</SelectItem>
                {BOUNTY_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {BOUNTY_STATUS_LABELS[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <TabsContent value={role} className={cn(!showingRows && 'p-4')}>
            <QueryView
              query={query}
              skeleton="app-my-bounties"
              isEmpty={(d) => d.items.length === 0}
              empty={{
                icon: BriefcaseBusiness,
                title:
                  role === 'requester'
                    ? status
                      ? 'No bounties with this status'
                      : 'You haven’t posted a bounty yet'
                    : 'You’re not assigned to any bounties yet',
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
                  <BountiesTable rows={data.items} role={role} />
                  <PaginationBar
                    page={data.page}
                    pages={data.pages}
                    total={data.total}
                    pageSize={data.page_size}
                    onPageChange={setPage}
                    itemLabel="bounties"
                    className="border-t px-4 py-3 sm:px-5"
                  />
                </>
              )}
            </QueryView>
          </TabsContent>
        </Tabs>
      </Card>
    </div>
  )
}
