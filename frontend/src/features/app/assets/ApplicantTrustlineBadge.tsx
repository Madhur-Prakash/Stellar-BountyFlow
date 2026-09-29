import { useBountyTrustlines } from '@/lib/api/queries/assets'

import { TrustlineBadge } from './TrustlineBadge'

/**
 * For the requester: whether an applicant's payout wallet can receive the bounty's asset. Renders nothing for
 * XLM bounties (no trustline is needed) or before the check has answered.
 */
export function ApplicantTrustlineBadge({
  bountyId,
  contributorId,
  enabled = true,
}: {
  bountyId: string
  contributorId: string
  enabled?: boolean
}) {
  const { data } = useBountyTrustlines(bountyId, enabled)
  if (!data?.requires_trustline) return null
  const applicant = data.applicants.find((a) => a.contributor_id === contributorId)
  if (!applicant) return null
  return <TrustlineBadge state={applicant.state} code={data.asset.code} />
}
