import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'

import { MonoValue } from '@/components/common/MonoValue'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-9 items-center justify-between gap-3 py-1.5">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  )
}

/** Funded vs required, escrow state and the contract link. */
export function EscrowPanel({ bounty }: { bounty: BountyDetail }) {
  const { data: config } = usePublicConfig()
  const escrow = bounty.escrow
  const asset = bounty.reward_asset.code
  const required = escrow?.required_amount ?? multiplyAmount(bounty.reward_amount, bounty.positions_available)
  const funded = escrow?.funded_amount ?? '0'
  const ratio = amountRatio(funded, required)
  const percent = Math.floor(ratio * 100)
  const contractHref =
    escrow?.explorer_url && /^https:\/\//i.test(escrow.explorer_url)
      ? escrow.explorer_url
      : contractExplorerUrl(config, escrow?.contract_id)

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>Escrow</CardTitle>
        <CardAction>
          <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="flex items-baseline justify-between gap-2 text-[0.8125rem]">
            <span className="text-muted-foreground">In escrow</span>
            <span className="text-muted-foreground tabular-nums">{percent}%</span>
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-1.5">
            <span className="amount text-lg leading-tight">{formatAmount(funded)}</span>
            <span className="text-sm text-muted-foreground tabular-nums">
              / {formatAmount(required)} {asset}
            </span>
          </div>
          <Progress
            value={ratio * 100}
            className="mt-3 h-1.5"
            aria-label={`Escrow funded ${percent} percent`}
          />
        </div>

        <dl className="divide-y border-t text-sm">
          <Row label="State">
            {escrow ? (STATE_LABEL[escrow.state] ?? humanize(escrow.state)) : 'Escrow not created yet'}
          </Row>
          {escrow && isPositiveAmount(escrow.paid_out_amount) && (
            <Row label="Paid out">
              <span className="tabular-nums">
                {formatAmount(escrow.paid_out_amount)} {asset}
              </span>
            </Row>
          )}
          {escrow && isPositiveAmount(escrow.refunded_amount) && (
            <Row label="Refunded">
              <span className="tabular-nums">
                {formatAmount(escrow.refunded_amount)} {asset}
              </span>
            </Row>
          )}
          <Row label="Network">{networkDisplayName(escrow?.network ?? bounty.network)}</Row>
          <Row label="Contract">
            {escrow?.contract_id ? (
              <MonoValue
                value={escrow.contract_id}
                label="escrow contract id"
                href={contractHref}
                lead={4}
                tail={4}
                className="-mr-2 justify-end"
              />
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </Row>
          {escrow?.last_reconciled_at && (
            <Row label="Last checked on-chain">{formatRelative(escrow.last_reconciled_at)}</Row>
          )}
        </dl>

        {contractHref && (
          <a
            href={contractHref}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="inline-flex min-h-9 items-center gap-1.5 text-sm font-medium text-primary-emphasis hover:underline"
          >
            Verify escrow on explorer <ExternalLink className="size-3.5" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </CardContent>
    </Card>
  )
}
