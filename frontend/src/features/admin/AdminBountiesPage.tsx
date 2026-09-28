import { Ban, BriefcaseBusiness, Eye, EyeOff, MoreHorizontal, Pin, PinOff } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { BountyStatusBadge } from '@/components/bounty/BountyStatusBadge'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { DataTable, type Column } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useDebounce } from '@/hooks/useDebounce'
import { errorMessage } from '@/lib/api/client'
import { useAdminBounties, useModerateBounty } from '@/lib/api/queries/admin'
import { useMe } from '@/lib/api/queries/auth'
import { useFeatureBounty } from '@/lib/api/queries/bounties'
import {
  BOUNTY_STATUSES,
  type BountyStatus,
  type BountySummary,
  type ModerationAction,
} from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { hasPermission } from '@/lib/permissions'

import { DateCell, FilterBar, FilterSelect, PagedResults, SearchField, UserCell } from './admin-shared'
import { ADMIN_PAGE_SIZE, bountyPath, scrollToTop, useFilteredPage } from './admin-utils'

/** Statuses from which a moderator cancel can never succeed. */
const NOT_CANCELLABLE: ReadonlySet<BountyStatus> = new Set(['CANCELLED', 'CANCEL_REQUESTED', 'COMPLETED'])

const MODERATION_COPY: Record<
  ModerationAction,
  { title: string; confirm: string; success: string; destructive: boolean; description: string }
> = {
  HIDE: {
    title: 'Hide bounty',
    confirm: 'Hide bounty',
    success: 'Bounty hidden from the marketplace.',
    destructive: true,
    description: 'Hidden bounties are removed from the public marketplace until a moderator unhides them.',
  },
  UNHIDE: {
    title: 'Unhide bounty',
    confirm: 'Unhide bounty',
    success: 'Bounty is visible in the marketplace again.',
    destructive: false,
    description:
      'The bounty becomes visible in the public marketplace again, subject to its own visibility setting.',
  },
  CANCEL: {
    title: 'Cancel bounty',
    confirm: 'Cancel bounty',
    success: 'Cancellation recorded.',
    destructive: true,
    description:
      'Unfunded draft, open, or expired bounties are cancelled immediately. Bounties with work in progress or funds in escrow move to “Cancel requested” first. Pending applications are rejected.',
  },
}

export default function AdminBountiesPage() {
  const { data: me } = useMe()
  const canModerate = hasPermission(me, 'bounty:moderate')
  const canFeature = hasPermission(me, 'bounty:feature')

  const [search, setSearch] = useState('')
  const q = useDebounce(search.trim(), 300)
  const [status, setStatus] = useState<BountyStatus | undefined>(undefined)
  const [page, setPage] = useFilteredPage(`${q}|${status ?? ''}`)
  const query = useAdminBounties({ q: q || undefined, status, page, page_size: ADMIN_PAGE_SIZE })

  const moderate = useModerateBounty()
  const feature = useFeatureBounty()

  const [target, setTarget] = useState<{ bounty: BountySummary; action: ModerationAction } | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const openModeration = (bounty: BountySummary, action: ModerationAction) => {
    setTarget({ bounty, action })
    setDialogOpen(true)
  }

  const toggleFeatured = (bounty: BountySummary) => {
    const featured = !bounty.is_featured
    feature.mutate(
      { bountyId: bounty.id, featured },
      {
        onSuccess: () =>
          toast.success(
            featured ? `“${bounty.title}” is now featured.` : `“${bounty.title}” is no longer featured.`,
          ),
        onError: (e) => toast.error(errorMessage(e)),
      },
    )
  }

  const columns: Column<BountySummary>[] = [
    {
      key: 'title',
      header: 'Bounty',
      cell: (b) => (
        <div className="max-w-sm min-w-0 text-left">
          <Link to={bountyPath(b)} className="line-clamp-2 font-medium hover:underline">
            {b.title}
          </Link>
          {(b.is_featured || b.is_hidden) && (
            <div className="mt-1 flex flex-wrap gap-1">
              {b.is_hidden && (
                <Badge variant="warning">
                  <EyeOff aria-hidden /> Hidden
                </Badge>
              )}
              {b.is_featured && (
                <Badge variant="info">
                  <Pin aria-hidden /> Featured
                </Badge>
              )}
            </div>
          )}
        </div>
      ),
    },
    { key: 'requester', header: 'Requester', cell: (b) => <UserCell user={b.requester} /> },
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
        <div className="whitespace-nowrap tabular-nums">
          <span className="font-medium">{formatAmount(b.reward_amount)}</span>{' '}
          <span className="text-muted-foreground">{b.reward_asset.code}</span>
          {b.positions_available > 1 && (
            <div className="text-xs text-muted-foreground">
              × {b.positions_available} positions, {formatAmount(b.total_reward)} total
            </div>
          )}
        </div>
      ),
    },
    { key: 'created', header: 'Created', cell: (b) => <DateCell iso={b.created_at} /> },
  ]

  if (canModerate || canFeature) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      hideLabelOnMobile: true,
      cell: (b) => {
        const busy =
          (moderate.isPending && moderate.variables?.id === b.id) ||
          (feature.isPending && feature.variables?.bountyId === b.id)
        return (
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                disabled={busy}
                aria-label={`Moderation actions for ${b.title}`}
              >
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Moderate</DropdownMenuLabel>
              {canModerate && (
                <>
                  {b.is_hidden ? (
                    <DropdownMenuItem className="min-h-10" onSelect={() => openModeration(b, 'UNHIDE')}>
                      <Eye aria-hidden /> Unhide
                    </DropdownMenuItem>
                  ) : (
                    <DropdownMenuItem className="min-h-10" onSelect={() => openModeration(b, 'HIDE')}>
                      <EyeOff aria-hidden /> Hide from marketplace
                    </DropdownMenuItem>
                  )}
                  {!NOT_CANCELLABLE.has(b.status) && (
                    <DropdownMenuItem
                      className="min-h-10"
                      variant="destructive"
                      onSelect={() => openModeration(b, 'CANCEL')}
                    >
                      <Ban aria-hidden /> Cancel bounty
                    </DropdownMenuItem>
                  )}
                </>
              )}
              {canFeature && (
                <>
                  {canModerate && <DropdownMenuSeparator />}
                  <DropdownMenuItem className="min-h-10" onSelect={() => toggleFeatured(b)}>
                    {b.is_featured ? <PinOff aria-hidden /> : <Pin aria-hidden />}
                    {b.is_featured ? 'Unfeature bounty' : 'Feature bounty'}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )
      },
    })
  }

  const copy = target ? MODERATION_COPY[target.action] : MODERATION_COPY.HIDE
  const filtered = !!q || !!status

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Bounties"
        description="Every bounty on the platform, including drafts and hidden ones. Hide, unhide, cancel, or feature bounties."
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Bounties' }]}
      />

      <FilterBar>
        <SearchField
          id="admin-bounties-search"
          label="Search bounties"
          placeholder="Search by title or slug"
          value={search}
          onChange={setSearch}
          maxLength={200}
        />
        <FilterSelect
          id="admin-bounties-status"
          label="Filter by status"
          value={status}
          onChange={setStatus}
          options={BOUNTY_STATUSES}
          labels={BOUNTY_STATUS_LABELS}
          allLabel="All statuses"
        />
      </FilterBar>

      <PagedResults
        query={query}
        skeleton="admin-bounties"
        label="Bounties"
        itemLabel="bounties"
        errorTitle="Could not load bounties"
        empty={{
          icon: BriefcaseBusiness,
          title: 'No bounties yet',
          description: 'Bounties appear here as soon as requesters create them.',
        }}
        filtered={filtered}
        onClearFilters={() => {
          setSearch('')
          setStatus(undefined)
        }}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
      >
        {(items) => <DataTable rows={items} columns={columns} getKey={(b) => b.id} caption="All bounties" />}
      </PagedResults>

      <ReasonDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title={copy.title}
        description={
          target ? (
            <>
              <span className="font-medium text-foreground">“{target.bounty.title}”.</span> {copy.description}{' '}
              The reason is recorded in the audit log.
            </>
          ) : undefined
        }
        label="Reason"
        minLength={5}
        maxLength={1000}
        confirmLabel={copy.confirm}
        destructive={copy.destructive}
        pending={moderate.isPending}
        onConfirm={async (reason) => {
          if (!target) return
          try {
            await moderate.mutateAsync({ id: target.bounty.id, body: { action: target.action, reason } })
            toast.success(copy.success)
          } catch (e) {
            toast.error(errorMessage(e))
            throw e
          }
        }}
      />
    </div>
  )
}
