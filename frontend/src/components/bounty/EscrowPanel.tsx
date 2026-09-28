import { ExternalLink, ShieldCheck } from 'lucide-react'

import { MonoValue } from '@/components/common/MonoValue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { BountyDetail, EscrowState } from '@/lib/api/types'
import { formatRelative, humanize } from '@/lib/format'
import { amountRatio, formatAmount, isPositiveAmount, multiplyAmount } from '@/lib/money'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'

import { FundingStatusBadge } from './FundingStatusBadge'

const STATE_LABEL: Record<EscrowState, string> = {
  NOT_CREATED: 'Escrow not created yet',
  AWAITING_FUNDING: 'Awaiting funding',
  FUNDED: 'Holding funds',
  CANCEL_REQUESTED: 'Cancellation requested',
  DISPUTED: 'Locked by dispute',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
}

/** Funded vs required, escrow state and the contract link. */
export function EscrowPanel({ bounty }: { bounty: BountyDetail }) {
  const { data: config } = usePublicConfig()
  const escrow = bounty.escrow
  const asset = bounty.reward_asset.code
  const required = escrow?.required_amount ?? multiplyAmount(bounty.reward_amount, bounty.positions_available)
  const funded = escrow?.funded_amount ?? '0'
  const ratio = amountRatio(funded, required)
  const contractHref =
    escrow?.explorer_url && /^https:\/\//i.test(escrow.explorer_url)
      ? escrow.explorer_url
      : contractExplorerUrl(config, escrow?.contract_id)

  return (
    <Card className="gap-4">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="size-4 text-muted-foreground" aria-hidden /> Escrow
        </CardTitle>
        <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm text-muted-foreground">In escrow</span>
            <span className="text-sm text-muted-foreground tabular-nums">{Math.floor(ratio * 100)}%</span>
          </div>
          <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">
            {formatAmount(funded)}{' '}
            <span className="text-sm font-normal text-muted-foreground">
              / {formatAmount(required)} {asset}
            </span>
          </div>
          <Progress
            value={ratio * 100}
            className="mt-3 h-1.5"
            aria-label={`Escrow funded ${Math.floor(ratio * 100)} percent`}
          />
        </div>

        <dl className="space-y-2 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">State</dt>
            <dd>
              {escrow ? (STATE_LABEL[escrow.state] ?? humanize(escrow.state)) : 'Escrow not created yet'}
            </dd>
          </div>
          {escrow && isPositiveAmount(escrow.paid_out_amount) && (
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Paid out</dt>
              <dd className="tabular-nums">
                {formatAmount(escrow.paid_out_amount)} {asset}
              </dd>
            </div>
          )}
          {escrow && isPositiveAmount(escrow.refunded_amount) && (
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Refunded</dt>
              <dd className="tabular-nums">
                {formatAmount(escrow.refunded_amount)} {asset}
              </dd>
            </div>
          )}
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">Network</dt>
            <dd>{networkDisplayName(escrow?.network ?? bounty.network)}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-muted-foreground">Contract</dt>
            <dd className="min-w-0">
              {escrow?.contract_id ? (
                <MonoValue
                  value={escrow.contract_id}
                  label="escrow contract id"
                  href={contractHref}
                  lead={4}
                  tail={4}
                />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </dd>
          </div>
          {escrow?.last_reconciled_at && (
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Last checked on-chain</dt>
              <dd>{formatRelative(escrow.last_reconciled_at)}</dd>
            </div>
          )}
        </dl>

        {contractHref && (
          <a
            href={contractHref}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary-emphasis hover:underline"
          >
            Verify escrow on explorer <ExternalLink className="size-3.5" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </CardContent>
    </Card>
  )
}
