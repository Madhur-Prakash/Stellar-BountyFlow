import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { useMemo } from 'react'

import { chainApi, fundingApi, paymentsApi, payoutsApi, transactionsApi } from '../endpoints'
import type {
  BlockchainTransaction,
  ChainPrepareRequest,
  FundingPrepareRequest,
  PageParams,
  PaymentsParams,
  PayoutPrepareRequest,
} from '../types'
import { qk } from './keys'

export function useBountyFunding(bountyId: string | undefined) {
  return useQuery({
    queryKey: qk.bounties.funding(bountyId ?? ''),
    queryFn: () => fundingApi.get(bountyId!),
    enabled: !!bountyId,
  })
}

export function useBountyTransactions(bountyId: string | undefined) {
  return useQuery({
    queryKey: qk.bounties.transactions(bountyId ?? ''),
    queryFn: () => transactionsApi.forBounty(bountyId!),
    enabled: !!bountyId,
  })
}

/**
 * Contributor addresses currently assigned on-chain (contract state "Assigned")
 * for a bounty, replayed from its confirmed transactions: ASSIGN adds the
 * destination; PAYOUT / DISPUTE_RESOLVE (destination) and CANCEL_CONSENT
 * (source) end the assignment.
 */
export function onchainAssignees(transactions: BlockchainTransaction[] | undefined): Set<string> {
  const assigned = new Set<string>()
  const confirmed = (transactions ?? [])
    .filter((t) => t.status === 'CONFIRMED')
    .sort((a, b) => (a.confirmed_at ?? a.created_at).localeCompare(b.confirmed_at ?? b.created_at))
  for (const t of confirmed) {
    if (t.transaction_type === 'ASSIGN' && t.destination_address) assigned.add(t.destination_address)
    if (
      (t.transaction_type === 'PAYOUT' || t.transaction_type === 'DISPUTE_RESOLVE') &&
      t.destination_address
    ) {
      assigned.delete(t.destination_address)
    }
    if (t.transaction_type === 'CANCEL_CONSENT' && t.source_address) assigned.delete(t.source_address)
  }
  return assigned
}

export function useOnchainAssignees(bountyId: string | undefined) {
  const query = useBountyTransactions(bountyId)
  const assignees = useMemo(() => onchainAssignees(query.data), [query.data])
  return { ...query, assignees }
}

export function useMyTransactions(params: PageParams = {}) {
  return useQuery({
    queryKey: qk.transactions.mine(params),
    queryFn: () => transactionsApi.mine(params),
    placeholderData: keepPreviousData,
  })
}

export function useTransaction(idOrHash: string | undefined) {
  return useQuery({
    queryKey: qk.transactions.detail(idOrHash ?? ''),
    queryFn: () => transactionsApi.get(idOrHash!),
    enabled: !!idOrHash,
  })
}

export function useMyPayments(params: PaymentsParams = {}) {
  return useQuery({
    queryKey: qk.payments.mine(params),
    queryFn: () => paymentsApi.mine(params),
    placeholderData: keepPreviousData,
  })
}

/** Everything that can change after an on-chain action settles. */
export function invalidateAfterChainAction(client: QueryClient, bountyId?: string | null) {
  if (bountyId) {
    client.invalidateQueries({ queryKey: qk.bounties.detail(bountyId) })
    client.invalidateQueries({ queryKey: qk.bounties.funding(bountyId) })
    client.invalidateQueries({ queryKey: qk.bounties.transactions(bountyId) })
  }
  client.invalidateQueries({ queryKey: qk.bounties.all })
  client.invalidateQueries({ queryKey: qk.transactions.all })
  client.invalidateQueries({ queryKey: qk.payments.all })
  client.invalidateQueries({ queryKey: qk.submissions.all })
  client.invalidateQueries({ queryKey: qk.disputes.all })
  client.invalidateQueries({ queryKey: qk.dashboard })
  client.invalidateQueries({ queryKey: qk.analytics.all })
  client.invalidateQueries({ queryKey: qk.notifications.all })
  client.invalidateQueries({ queryKey: qk.admin.all })
}

export function usePrepareChainAction() {
  return useMutation({
    mutationFn: ({ bountyId, body }: { bountyId: string; body: ChainPrepareRequest }) =>
      chainApi.prepare(bountyId, body),
  })
}

export function usePrepareFunding() {
  return useMutation({
    mutationFn: ({ bountyId, body }: { bountyId: string; body: FundingPrepareRequest }) =>
      fundingApi.prepare(bountyId, body),
  })
}

export function useSubmitFunding() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      bountyId,
      transactionId,
      signedXdr,
    }: {
      bountyId: string
      transactionId: string
      signedXdr: string
    }) => fundingApi.submit(bountyId, { transaction_id: transactionId, signed_xdr: signedXdr }),
    onSuccess: (_tx, vars) => invalidateAfterChainAction(client, vars.bountyId),
  })
}

export function usePreparePayout() {
  return useMutation({
    mutationFn: ({ bountyId, body }: { bountyId: string; body: PayoutPrepareRequest }) =>
      payoutsApi.prepare(bountyId, body),
  })
}

export function useSubmitPayout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      bountyId,
      transactionId,
      signedXdr,
    }: {
      bountyId: string
      transactionId: string
      signedXdr: string
    }) => payoutsApi.submit(bountyId, { transaction_id: transactionId, signed_xdr: signedXdr }),
    onSuccess: (_tx, vars) => invalidateAfterChainAction(client, vars.bountyId),
  })
}

export function useSubmitTransaction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ transactionId, signedXdr }: { transactionId: string; signedXdr: string }) =>
      transactionsApi.submit(transactionId, { signed_xdr: signedXdr }),
    onSuccess: (tx) => invalidateAfterChainAction(client, tx.bounty_id),
  })
}
