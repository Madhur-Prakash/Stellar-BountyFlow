import { Layers } from 'lucide-react'

import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { Button } from '@/components/ui/button'
import { chainApi } from '@/lib/api/endpoints'
import type { Submission } from '@/lib/api/types'
import { addAmounts, formatAmount } from '@/lib/money'

/**
 * "Pay N contributors": one `batch_release` for the selected approved submissions, signed once. The contract
 * pays every leg or none, and BountyFlow marks them paid only after each leg reads as paid on-chain.
 */
export function BatchPayBar({
  bountyId,
  selected,
  milestones,
  maxBatch,
  onClear,
  onConfirmed,
}: {
  bountyId: string
  selected: Submission[]
  /** A milestone bounty pays milestones rather than contributors. */
  milestones: boolean
  maxBatch: number
  onClear: () => void
  onConfirmed: () => void
}) {
  if (selected.length === 0) return null
  const total = addAmounts(...selected.map((s) => s.payment?.amount ?? '0'))
  const code = selected[0]?.payment?.asset.code ?? 'XLM'
  const noun = milestones ? 'milestones' : 'contributors'
  const tooMany = selected.length > maxBatch
  return (
    <div
      role="region"
      aria-label="Batch payout"
      className="sticky top-2 z-10 flex flex-wrap items-center gap-3 rounded-xl border bg-card px-4 py-3 shadow-soft"
    >
      <span className="text-sm">
        <span className="font-medium tabular-nums">{selected.length}</span> selected,{' '}
        <span className="amount font-medium">
          {formatAmount(total)} {code}
        </span>
      </span>
      {tooMany && <span className="text-sm text-warning">Up to {maxBatch} per transaction.</span>}
      <div className="ml-auto flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={onClear}>
          Clear
        </Button>
        <ChainActionButton
          size="sm"
          icon={Layers}
          label={`Pay ${selected.length} ${noun}`}
          title="Batch payout"
          description={`Release ${formatAmount(total)} ${code} to ${selected.length} ${noun} in one transaction.`}
          disabled={selected.length < 2 || tooMany}
          onConfirmed={onConfirmed}
          prepare={(wallet_address) =>
            chainApi.prepare(bountyId, {
              action: 'BATCH_PAYOUT',
              wallet_address,
              submission_ids: selected.map((s) => s.id),
            })
          }
        />
      </div>
    </div>
  )
}
