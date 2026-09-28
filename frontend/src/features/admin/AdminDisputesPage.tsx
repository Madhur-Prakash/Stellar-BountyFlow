import { Gavel, Hand, Info, Lock, Paperclip, Scale, Signature, X } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { MonoValue } from '@/components/common/MonoValue'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { DataTable, type Column } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorMessage } from '@/lib/api/client'
import { chainApi } from '@/lib/api/endpoints'
import { useAdminDisputes } from '@/lib/api/queries/admin'
import { usePublicConfig } from '@/lib/api/queries/config'
import { useMe } from '@/lib/api/queries/auth'
import { useAssignDispute, useResolveDispute } from '@/lib/api/queries/disputes'
import {
  DISPUTE_RESOLUTIONS,
  DISPUTE_STATUSES,
  type Dispute,
  type DisputeResolution,
  type DisputeStatus,
} from '@/lib/api/types'
import { DISPUTE_STATUS_LABELS } from '@/lib/format'
import { hasPermission } from '@/lib/permissions'

import {
  ClampedText,
  DateCell,
  DisputeStatusBadge,
  FilterBar,
  FilterSelect,
  PagedResults,
  UserCell,
} from './admin-shared'
import {
  ADMIN_PAGE_SIZE,
  bountyPath,
  DISPUTE_RESOLUTION_LABELS,
  OPEN_DISPUTE_STATUSES,
  scrollToTop,
  useFilteredPage,
} from './admin-utils'

/**
 * Executes a recorded release/refund decision on-chain. The escrow contract
 * only accepts RESOLVE_DISPUTE from the arbiter address fixed when the escrow
 * was created, so that wallet must sign.
 */
function ExecuteResolutionButton({
  dispute,
  size = 'default',
}: {
  dispute: Dispute
  size?: 'default' | 'sm'
}) {
  const { data: config } = usePublicConfig()
  const arbiter = config?.arbiter_address ?? null
  const pay = dispute.resolution === 'RELEASE_TO_CONTRIBUTOR'
  return (
    <ChainActionButton
      size={size}
      icon={Signature}
      label="Sign as arbiter"
      title="Execute dispute decision"
      description={
        pay
          ? `Release the escrowed reward for “${dispute.bounty.title}” to the contributor.`
          : `Release the contributor’s claim on “${dispute.bounty.title}” so the requester can refund the escrow.`
      }
      prepare={(wallet_address) =>
        chainApi.prepare(dispute.bounty.id, {
          action: 'RESOLVE_DISPUTE',
          wallet_address,
          dispute_id: dispute.id,
        })
      }
    >
      <p className="text-muted-foreground">
        The escrow’s arbiter wallet must sign this transaction
        {arbiter ? (
          <>
            {' '}
            (<MonoValue value={arbiter} label="arbiter address" lead={4} tail={4} />)
          </>
        ) : null}
        . Connect that wallet in Freighter before continuing; any other wallet is rejected by the contract.
      </p>
    </ChainActionButton>
  )
}

const ESCROW_NOTE =
  'This records the off-chain decision. If the reward is held in the on-chain escrow, the arbiter wallet must then sign the RESOLVE_DISPUTE chain action to move the funds.'

export default function AdminDisputesPage() {
  const { data: me } = useMe()
  const canResolve = hasPermission(me, 'dispute:resolve')

  const [status, setStatus] = useState<DisputeStatus | undefined>(undefined)
  const [page, setPage] = useFilteredPage(status ?? '')
  const query = useAdminDisputes({ status, page, page_size: ADMIN_PAGE_SIZE })

  const assign = useAssignDispute()
  const resolve = useResolveDispute()

  const [target, setTarget] = useState<Dispute | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [resolution, setResolution] = useState<DisputeResolution>('RELEASE_TO_CONTRIBUTOR')
  const [justResolved, setJustResolved] = useState<Dispute | null>(null)
  const resolutionId = useId()

  const assignToMe = (dispute: Dispute) => {
    assign.mutate(dispute.id, {
      onSuccess: () =>
        toast.success(`You are now the moderator for the dispute on “${dispute.bounty.title}”.`),
      onError: (e) => toast.error(errorMessage(e)),
    })
  }

  const columns: Column<Dispute>[] = [
    {
      key: 'bounty',
      header: 'Bounty',
      cell: (d) => (
        <Link
          to={bountyPath(d.bounty)}
          className="line-clamp-2 max-w-60 text-left font-medium hover:underline"
        >
          {d.bounty.title}
        </Link>
      ),
    },
    { key: 'raised_by', header: 'Raised by', cell: (d) => <UserCell user={d.raised_by} /> },
    { key: 'reason', header: 'Reason', cell: (d) => <ClampedText text={d.reason} /> },
    {
      key: 'status',
      header: 'Status',
      cell: (d) => (
        <div className="flex flex-col items-end gap-1 md:items-start">
          <DisputeStatusBadge status={d.status} />
          {d.resolution && (
            <span className="text-xs text-muted-foreground">{DISPUTE_RESOLUTION_LABELS[d.resolution]}</span>
          )}
          {d.escrow_frozen_onchain && (
            <Badge variant="info">
              <Lock aria-hidden /> Escrow frozen
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: 'moderator',
      header: 'Moderator',
      cell: (d) =>
        d.assigned_moderator ? (
          <UserCell user={d.assigned_moderator} />
        ) : (
          <span className="text-sm text-muted-foreground">Unassigned</span>
        ),
    },
    {
      key: 'evidence',
      header: 'Evidence',
      className: 'text-right',
      cell: (d) => (
        <span
          className="inline-flex items-center gap-1 tabular-nums"
          title={`${d.evidence.length} evidence items`}
        >
          <Paperclip className="size-3.5 text-muted-foreground" aria-hidden />
          {d.evidence.length}
          <span className="sr-only"> evidence items</span>
        </span>
      ),
    },
    { key: 'created', header: 'Raised', cell: (d) => <DateCell iso={d.created_at} /> },
  ]

  if (canResolve) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      hideLabelOnMobile: true,
      cell: (d) => {
        if (!OPEN_DISPUTE_STATUSES.has(d.status)) {
          if (d.requires_onchain_execution) {
            return (
              <div className="flex flex-col items-end gap-1">
                <ExecuteResolutionButton dispute={d} />
                <span className="text-xs text-muted-foreground">Awaiting arbiter signature</span>
              </div>
            )
          }
          return <span className="text-xs text-muted-foreground">Closed</span>
        }
        const assignedToMe = !!me && d.assigned_moderator?.id === me.id
        return (
          <div className="flex flex-wrap justify-end gap-2">
            {!assignedToMe && (
              <Button
                variant="outline"
                disabled={assign.isPending && assign.variables === d.id}
                aria-label={`Assign the dispute on ${d.bounty.title} to me`}
                onClick={() => assignToMe(d)}
              >
                <Hand aria-hidden /> Assign to me
              </Button>
            )}
            <Button
              disabled={resolve.isPending && resolve.variables?.id === d.id}
              aria-label={`Resolve the dispute on ${d.bounty.title}`}
              onClick={() => {
                setTarget(d)
                setResolution('RELEASE_TO_CONTRIBUTOR')
                setDialogOpen(true)
              }}
            >
              <Gavel aria-hidden /> Resolve
            </Button>
          </div>
        )
      },
    })
  }

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Disputes"
        description={
          canResolve
            ? 'Disputes raised by requesters and contributors. Assign one to yourself, review the evidence, and record a decision.'
            : 'Disputes raised by requesters and contributors.'
        }
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Disputes' }]}
      />

      {justResolved && (
        <Alert variant="info" className="mb-5" role="status">
          <Info aria-hidden />
          <AlertTitle>Decision recorded for “{justResolved.bounty.title}”</AlertTitle>
          <AlertDescription>
            {justResolved.resolution === 'DISMISSED' ? (
              <p>The dispute was dismissed.</p>
            ) : justResolved.requires_onchain_execution ? (
              <>
                <p>
                  Decision: {DISPUTE_RESOLUTION_LABELS[justResolved.resolution ?? resolution].toLowerCase()}.
                  The reward is frozen in the on-chain escrow, so the arbiter wallet must now sign the{' '}
                  on-chain resolution before any funds move.
                </p>
                <div className="my-1">
                  <ExecuteResolutionButton dispute={justResolved} size="sm" />
                </div>
              </>
            ) : (
              <p>
                Decision: {DISPUTE_RESOLUTION_LABELS[justResolved.resolution ?? resolution].toLowerCase()}.
                The escrow was not frozen on-chain, so the decision is applied in BountyFlow; any payout still
                needs the requester’s signature.
              </p>
            )}
            <p>
              <Link
                to={bountyPath(justResolved.bounty)}
                className="inline-flex items-center gap-1 font-medium"
              >
                Open the bounty
              </Link>
            </p>
          </AlertDescription>
          <AlertAction>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Dismiss this notice"
              onClick={() => setJustResolved(null)}
            >
              <X />
            </Button>
          </AlertAction>
        </Alert>
      )}

      <FilterBar>
        <FilterSelect
          id="admin-disputes-status"
          label="Filter by status"
          value={status}
          onChange={setStatus}
          options={DISPUTE_STATUSES}
          labels={DISPUTE_STATUS_LABELS}
          allLabel="All statuses"
        />
      </FilterBar>

      <PagedResults
        query={query}
        skeleton="admin-disputes"
        label="Disputes"
        itemLabel="disputes"
        errorTitle="Could not load disputes"
        empty={{
          icon: Scale,
          title: 'No disputes',
          description: 'Disputes raised on bounties will appear here.',
        }}
        filtered={!!status}
        onClearFilters={() => setStatus(undefined)}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
      >
        {(items) => (
          <DataTable rows={items} columns={columns} getKey={(d) => d.id} caption="Bounty disputes" />
        )}
      </PagedResults>

      <ReasonDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Resolve dispute"
        description={
          target ? (
            <>
              <span className="font-medium text-foreground">“{target.bounty.title}”</span>, raised by @
              {target.raised_by.username}. {ESCROW_NOTE}
            </>
          ) : (
            ESCROW_NOTE
          )
        }
        label="Decision note"
        minLength={10}
        maxLength={5000}
        confirmLabel="Record decision"
        pending={resolve.isPending}
        onConfirm={async (note) => {
          if (!target) return
          try {
            const updated = await resolve.mutateAsync({ id: target.id, body: { resolution, note } })
            setJustResolved(updated)
            toast.success('Dispute decision recorded.')
          } catch (e) {
            toast.error(errorMessage(e))
            throw e
          }
        }}
      >
        <div className="space-y-2">
          <Label htmlFor={resolutionId}>Decision</Label>
          <Select value={resolution} onValueChange={(v) => setResolution(v as DisputeResolution)}>
            <SelectTrigger id={resolutionId} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DISPUTE_RESOLUTIONS.map((r) => (
                <SelectItem key={r} value={r}>
                  {DISPUTE_RESOLUTION_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </ReasonDialog>
    </div>
  )
}
