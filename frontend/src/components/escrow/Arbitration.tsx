import { Signature } from 'lucide-react'

import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { MonoValue } from '@/components/common/MonoValue'
import { Bones } from '@/components/layout/Bones'
import { ListSkeleton } from '@/components/layout/LoadingState'
import { Badge } from '@/components/ui/badge'
import { errorMessage } from '@/lib/api/client'
import { chainApi } from '@/lib/api/endpoints'
import { useArbitration } from '@/lib/api/queries/escrow'
import type { Arbitration, Dispute } from '@/lib/api/types'
import { formatAmount, tryParseAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

function ApprovalBar({ approvals, threshold }: { approvals: number; threshold: number }) {
  const pct = threshold > 0 ? Math.min(100, Math.round((approvals / threshold) * 100)) : 0
  return (
    <div
      role="progressbar"
      aria-label="Arbiter approvals"
      aria-valuemin={0}
      aria-valuemax={threshold}
      aria-valuenow={Math.min(approvals, threshold)}
      aria-valuetext={`${approvals} of ${threshold} approvals`}
      className="h-1.5 overflow-hidden rounded-full bg-muted"
    >
      <div
        className="h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

function Decision({ a }: { a: Arbitration }) {
  if (a.contributor_amount === null) return null
  const toContributor = formatAmount(a.contributor_amount)
  const rest = tryParseAmount(a.requester_amount)
  return (
    <p className="text-sm">
      <span className="text-muted-foreground">Decision: </span>
      {a.resolution === 'REFUND_TO_REQUESTER'
        ? 'the contributor’s claim is released so the requester can refund.'
        : rest !== null && rest > 0n
          ? `${toContributor} to the contributor, ${formatAmount(a.requester_amount)} back to the requester.`
          : `${toContributor} to the contributor.`}
    </p>
  )
}

function ArbitrationBody({ a, walletHint }: { a: Arbitration; walletHint: boolean }) {
  return (
    <div className="space-y-3 text-sm">
      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-medium tabular-nums">
            {a.approvals} of {a.threshold} approval{a.threshold === 1 ? '' : 's'}
          </span>
          {a.executed ? (
            <Badge variant="info">Executed on-chain</Badge>
          ) : !a.escrow_frozen ? (
            <Badge variant="muted">Escrow not frozen</Badge>
          ) : null}
        </div>
        <ApprovalBar approvals={a.approvals} threshold={a.threshold} />
      </div>
      <Decision a={a} />
      <ul className="divide-y rounded-lg border" aria-label="Arbiters">
        {a.arbiters.map((arb) => {
          const differs = !arb.approved && arb.contributor_amount !== null
          return (
            <li
              key={arb.address}
              className="flex min-h-10 flex-wrap items-center justify-between gap-2 px-3 py-2"
            >
              <div className="flex min-w-0 flex-col">
                <MonoValue value={arb.address} label="arbiter address" lead={4} tail={4} />
                <span className="mt-0.5 text-xs text-muted-foreground">
                  {arb.staff
                    ? `${arb.staff.display_name} (@${arb.staff.username})`
                    : 'No staff account linked'}
                </span>
              </div>
              <Badge variant={arb.approved ? 'info' : differs ? 'warning' : 'muted'}>
                {arb.approved ? 'Approved' : differs ? 'Voted another split' : 'Waiting'}
              </Badge>
            </li>
          )
        })}
      </ul>
      {walletHint && a.my_arbiter_wallets.length > 0 && a.can_vote && (
        <p className="text-muted-foreground">
          Connect your arbiter wallet (
          <MonoValue value={a.my_arbiter_wallets[0]} label="your arbiter address" lead={4} tail={4} />) in
          Freighter first. The contract only counts wallets in this escrow’s arbiter set.
        </p>
      )}
      {!a.can_vote && a.vote_blocked_reason && !a.executed && (
        <p className="text-muted-foreground">{a.vote_blocked_reason}</p>
      )}
    </div>
  )
}

/** The dispute's arbiter set, live from the contract: who approved the decision and how far it is from executing. */
export function ArbitrationProgress({
  disputeId,
  walletHint = false,
  className,
}: {
  disputeId: string
  /** In the vote dialog: which of the viewer's wallets to connect. */
  walletHint?: boolean
  className?: string
}) {
  const q = useArbitration(disputeId)
  if (q.isError) {
    return <p className={cn('text-sm text-destructive', className)}>{errorMessage(q.error)}</p>
  }
  return (
    <div className={className}>
      <Bones name="arbitration-progress" loading={q.isPending} fallback={<ListSkeleton rows={3} />}>
        {q.data && <ArbitrationBody a={q.data} walletHint={walletHint} />}
      </Bones>
    </div>
  )
}

/**
 * An arbiter's approval of the recorded decision, signed with one of the escrow's arbiter wallets
 * (DISPUTE_VOTE). The contract executes the decision when the threshold of matching approvals is reached.
 */
export function ArbiterVoteButton({
  dispute,
  size = 'default',
}: {
  dispute: Dispute
  size?: 'default' | 'sm'
}) {
  const threshold = dispute.arbiter_threshold ?? 1
  return (
    <ChainActionButton
      size={size}
      icon={Signature}
      label="Sign as arbiter"
      title="Approve dispute decision"
      description={
        threshold > 1
          ? `Add your approval to the decision on “${dispute.bounty.title}”. Funds move once ${threshold} arbiters approve the same decision.`
          : `Approve the decision on “${dispute.bounty.title}”. Funds move when this approval is confirmed.`
      }
      prepare={(wallet_address) =>
        chainApi.prepare(dispute.bounty.id, {
          action: 'DISPUTE_VOTE',
          wallet_address,
          dispute_id: dispute.id,
        })
      }
    >
      <ArbitrationProgress disputeId={dispute.id} walletHint />
    </ChainActionButton>
  )
}
