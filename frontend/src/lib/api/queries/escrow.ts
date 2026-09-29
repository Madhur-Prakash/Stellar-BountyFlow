import { useQuery } from '@tanstack/react-query'

import { escrowApi } from '../endpoints'
import { qk } from './keys'

/** Escrow settings: review-window bounds, the arbiter set, batch and milestone limits. */
export function useEscrowConfig() {
  return useQuery({ queryKey: qk.escrow.config, queryFn: () => escrowApi.config(), staleTime: 5 * 60_000 })
}

/** The dispute's arbiter panel (live contract votes, the viewer's arbiter wallets). */
export function useArbitration(disputeId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: qk.escrow.arbitration(disputeId ?? ''),
    queryFn: () => escrowApi.arbitration(disputeId!),
    enabled: !!disputeId && enabled,
  })
}
