import { http, seg } from '../client'
import type { Arbitration, EscrowConfig, Milestone, MilestoneInput } from '../types'

/**
 * Escrow v2 reads and milestone authoring. The v2 chain actions (MILESTONE_PAYOUT, BATCH_PAYOUT, SUBMIT_WORK,
 * REQUEST_CHANGES, REJECT_SUBMISSION, CLAIM, DISPUTE_VOTE) go through `chainApi.prepare`.
 */
export const escrowApi = {
  config: () => http.get<EscrowConfig>('/escrow/config'),
  milestones: (bountyId: string) => http.get<Milestone[]>(`/bounties/${seg(bountyId)}/milestones`),
  replaceMilestones: (bountyId: string, milestones: MilestoneInput[]) =>
    http.put<Milestone[]>(`/bounties/${seg(bountyId)}/milestones`, { milestones }),
  arbitration: (disputeId: string) => http.get<Arbitration>(`/disputes/${seg(disputeId)}/arbitration`),
}
