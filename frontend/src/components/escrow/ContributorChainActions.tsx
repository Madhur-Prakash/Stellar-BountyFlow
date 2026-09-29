import { CircleDollarSign, Timer } from 'lucide-react'

import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { useCountdown } from '@/hooks/useCountdown'
import { chainApi } from '@/lib/api/endpoints'
import type { Submission } from '@/lib/api/types'

const RECORDABLE = new Set(['SUBMITTED', 'RESUBMITTED'])

/**
 * The contributor's on-chain steps for one submission: record it (starts the requester's review window) and,
 * once the window passed unanswered, claim the payment. Both are signed with the wallet assigned on-chain.
 */
export function ContributorChainActions({
  submission,
  size = 'sm',
}: {
  submission: Submission
  size?: 'sm' | 'default'
}) {
  const review = submission.onchain_review
  // The window can pass while the page is open; the contract re-checks it when the claim is signed.
  const clock = useCountdown(review?.state === 'PENDING' ? review.claimable_at : null)
  const canRecord =
    !!submission.can_record_onchain &&
    RECORDABLE.has(submission.status) &&
    (!review || review.state === 'CHANGES_REQUESTED')
  const canClaim = !!review && review.state === 'PENDING' && (review.can_claim || !!clock?.isPast)
  if (!canRecord && !canClaim) return null
  const what = submission.milestone ? `the milestone “${submission.milestone.title}”` : 'this work'
  return (
    <>
      {canRecord && (
        <ChainActionButton
          size={size}
          variant="outline"
          icon={Timer}
          label="Record on-chain"
          title="Record submission"
          description={`Record ${what} in the escrow. If the requester does not answer within the review window, you can claim the payment.`}
          prepare={(wallet_address) =>
            chainApi.prepare(submission.bounty_id, {
              action: 'SUBMIT_WORK',
              wallet_address,
              submission_id: submission.id,
            })
          }
        />
      )}
      {canClaim && (
        <ChainActionButton
          size={size}
          icon={CircleDollarSign}
          label="Claim payment"
          title="Claim payment"
          description={`The review window for ${what} passed without an answer. The escrow pays you directly.`}
          prepare={(wallet_address) =>
            chainApi.prepare(submission.bounty_id, {
              action: 'CLAIM',
              wallet_address,
              submission_id: submission.id,
            })
          }
        />
      )}
    </>
  )
}
