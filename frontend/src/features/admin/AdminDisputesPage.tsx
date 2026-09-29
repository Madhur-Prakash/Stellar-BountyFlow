import { Gavel, Hand, Info, Lock, Paperclip, Scale, Signature, X } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { MonoValue } from '@/components/common/MonoValue'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { ArbiterVoteButton } from '@/components/escrow/Arbitration'
import { PageHeader } from '@/components/layout/PageHeader'
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { errorMessage } from '@/lib/api/client'
import { chainApi } from '@/lib/api/endpoints'
import { useAdminDisputes } from '@/lib/api/queries/admin'
import { usePublicConfig } from '@/lib/api/queries/config'
import { useMe } from '@/lib/api/queries/auth'
import { useAssignDispute, useResolveDispute } from '@/lib/api/queries/disputes'
import { useArbitration } from '@/lib/api/queries/escrow'
import {
  DISPUTE_RESOLUTIONS,
  DISPUTE_STATUSES,
  type Dispute,
  type DisputeResolution,
  type DisputeStatus,
} from '@/lib/api/types'
import { approvalsLabel, needsArbiterVotes } from '@/lib/escrow'
import { DISPUTE_STATUS_LABELS } from '@/lib/format'
import { formatAmount, isValidAmount, normalizeAmount } from '@/lib/money'
import { hasPermission } from '@/lib/permissions'

import {
  AdminTable,
  DateCell,
  DisputeStatusBadge,
  FilterSelect,
  PagedResults,
  UserCell,
  type AdminColumn,
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
  // A v2 escrow with several arbiters, or a split, is executed by arbiter votes.
  if (needsArbiterVotes(dispute)) return <ArbiterVoteButton dispute={dispute} size={size} />
  return <SingleArbiterButton dispute={dispute} size={size} />
}

function SingleArbiterButton({ dispute, size }: { dispute: Dispute; size: 'default' | 'sm' }) {
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
        . Connect that wallet in Freighter first. The contract rejects any other wallet.
      </p>
    </ChainActionButton>
  )
}

const ESCROW_NOTE =
  'This records the decision. If the reward is held in on-chain escrow, the arbiter wallet then signs RESOLVE_DISPUTE to move the funds.'

/** A split is only executed on a frozen v2 escrow. */
const canSplit = (d: Dispute | null) => !!d?.escrow_frozen_onchain && (d.contract_version ?? 1) >= 2

/** SPLIT: what the contributor receives, bounded by their open reward (read from the escrow). */
function SplitAmountField({
  dispute,
  value,
  onChange,
}: {
  dispute: Dispute
  value: string
  onChange: (v: string) => void
}) {
  const id = useId()
  const { data } = useArbitration(dispute.id)
  const open = data?.position_value ?? null
  const invalid = value.trim() !== '' && !isValidAmount(value.trim())
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>Contributor receives</Label>
      <Input
        id={id}
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid}
        aria-describedby={`${id}-help`}
      />
      <p id={`${id}-help`} className="text-[0.8125rem] text-muted-foreground">
        {open
          ? `The contributor’s open reward is ${formatAmount(open)}. The rest goes back to the requester.`
          : 'The rest of the contributor’s open reward goes back to the requester.'}
      </p>
    </div>
  )
}

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
  const [splitAmount, setSplitAmount] = useState('')
  const [justResolved, setJustResolved] = useState<Dispute | null>(null)
  const resolutionId = useId()

  const assignToMe = (dispute: Dispute) => {
    assign.mutate(dispute.id, {
      onSuccess: () =>
        toast.success(`You are now the moderator for the dispute on “${dispute.bounty.title}”.`),
      onError: (e) => toast.error(errorMessage(e)),
    })
  }

  const columns: AdminColumn<Dispute>[] = [
    {
      key: 'bounty',
      header: 'Dispute',
      mobile: 'title',
      cell: (d) => (
        <div className="max-w-72 min-w-0 whitespace-normal lg:min-w-44">
          <Link
            to={bountyPath(d.bounty)}
            title={d.bounty.title}
            className="line-clamp-2 leading-5 font-medium hover:underline lg:line-clamp-1"
          >
            {d.bounty.title}
          </Link>
          <p
            className="line-clamp-2 text-xs leading-4 text-muted-foreground lg:line-clamp-1"
            title={d.reason}
          >
            {d.reason}
          </p>
        </div>
      ),
    },
    { key: 'raised_by', header: 'Raised by', cell: (d) => <UserCell user={d.raised_by} avatar={false} /> },
    {
      key: 'status',
      header: 'Status',
      mobile: 'aside',
      cell: (d) => (
        <div className="flex flex-col items-end gap-1 lg:items-start">
          <DisputeStatusBadge status={d.status} />
          {d.escrow_frozen_onchain && (
            <Badge variant="outline">
              <Lock aria-hidden /> Escrow frozen
            </Badge>
          )}
          {d.resolution && d.resolution !== 'DISMISSED' && (
            <span className="text-xs leading-4 text-muted-foreground">
              {DISPUTE_RESOLUTION_LABELS[d.resolution]}
            </span>
          )}
          {d.requires_onchain_execution && needsArbiterVotes(d) && (
            <span className="text-xs leading-4 text-muted-foreground tabular-nums">{approvalsLabel(d)}</span>
          )}
        </div>
      ),
    },
    {
      key: 'moderator',
      header: 'Moderator',
      cell: (d) =>
        d.assigned_moderator ? (
          <UserCell user={d.assigned_moderator} avatar={false} />
        ) : (
          <span className="text-muted-foreground">Unassigned</span>
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
      hideHeader: true,
      className: 'text-right',
      mobile: 'actions',
      cell: (d) => {
        if (!OPEN_DISPUTE_STATUSES.has(d.status)) {
          if (d.requires_onchain_execution) {
            return (
              <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                <span className="text-xs text-muted-foreground">Awaiting arbiter signature</span>
                <ExecuteResolutionButton dispute={d} size="sm" />
              </div>
            )
          }
          return <span className="text-xs text-muted-foreground">Closed</span>
        }
        const assignedToMe = !!me && d.assigned_moderator?.id === me.id
        return (
          <div className="flex flex-wrap gap-2 lg:flex-nowrap lg:justify-end">
            {!assignedToMe && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="lg:w-8 lg:px-0"
                    disabled={assign.isPending && assign.variables === d.id}
                    aria-label={`Assign the dispute on ${d.bounty.title} to me`}
                    onClick={() => assignToMe(d)}
                  >
                    <Hand aria-hidden /> <span className="lg:sr-only">Assign to me</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Assign to me</TooltipContent>
              </Tooltip>
            )}
            <Button
              size="sm"
              disabled={resolve.isPending && resolve.variables?.id === d.id}
              aria-label={`Resolve the dispute on ${d.bounty.title}`}
              onClick={() => {
                setTarget(d)
                setResolution('RELEASE_TO_CONTRIBUTOR')
                setSplitAmount('')
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
    <div>
      <PageHeader title="Disputes" breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Disputes' }]} />

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
                  The reward is frozen in the on-chain escrow, so{' '}
                  {needsArbiterVotes(justResolved) && (justResolved.arbiter_threshold ?? 1) > 1
                    ? `${justResolved.arbiter_threshold} arbiter wallets must now approve it on-chain`
                    : 'the arbiter wallet must now sign the on-chain resolution'}{' '}
                  before any funds move.
                </p>
                <div className="my-1">
                  <ExecuteResolutionButton dispute={justResolved} size="sm" />
                </div>
              </>
            ) : (
              <p>
                Decision: {DISPUTE_RESOLUTION_LABELS[justResolved.resolution ?? resolution].toLowerCase()}.
                The escrow was not frozen on-chain, so the decision is applied in BountyFlow. Any payout still
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
              size="icon-sm"
              aria-label="Dismiss this notice"
              onClick={() => setJustResolved(null)}
            >
              <X />
            </Button>
          </AlertAction>
        </Alert>
      )}

      <PagedResults
        query={query}
        skeleton="admin-disputes"
        label="Disputes"
        itemLabel="disputes"
        errorTitle="Could not load disputes"
        empty={{ icon: Scale, title: 'No disputes' }}
        filtered={!!status}
        onClearFilters={() => setStatus(undefined)}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <FilterSelect
            id="admin-disputes-status"
            label="Filter by status"
            value={status}
            onChange={setStatus}
            options={DISPUTE_STATUSES}
            labels={DISPUTE_STATUS_LABELS}
            allLabel="All statuses"
          />
        }
      >
        {(items) => (
          <AdminTable rows={items} columns={columns} getKey={(d) => d.id} caption="Bounty disputes" />
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
          const split = resolution === 'SPLIT'
          if (split && !isValidAmount(splitAmount.trim())) {
            toast.error('Enter what the contributor receives, up to 7 decimals.')
            throw new Error('split amount required')
          }
          try {
            const updated = await resolve.mutateAsync({
              id: target.id,
              body: {
                resolution,
                note,
                ...(split ? { contributor_amount: normalizeAmount(splitAmount.trim()) } : {}),
              },
            })
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
              {DISPUTE_RESOLUTIONS.filter((r) => r !== 'SPLIT' || canSplit(target)).map((r) => (
                <SelectItem key={r} value={r}>
                  {DISPUTE_RESOLUTION_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {resolution === 'SPLIT' && target && (
          <SplitAmountField dispute={target} value={splitAmount} onChange={setSplitAmount} />
        )}
      </ReasonDialog>
    </div>
  )
}
