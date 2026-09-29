import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { adminAssetsApi, assetsApi } from '../endpoints'
import type { AdminRewardAsset, CreateAssetRequest, UpdateAssetRequest } from '../types'
import { qk } from './keys'

/**
 * Enabled reward assets (XLM, USDC, …). Changes rarely: cached for a minute.
 *
 * `GET /assets` answers a bare array. `select` guarantees callers an array even so: a proxy or an error page
 * that answers something else must not take the marketplace filters down with it.
 */
export function useRewardAssets() {
  return useQuery({
    queryKey: qk.assets.registry,
    queryFn: () => assetsApi.list(),
    select: (data) => (Array.isArray(data) ? data : []),
    staleTime: 60_000,
  })
}

export function useWalletAssets(enabled = true) {
  return useQuery({ queryKey: qk.assets.wallets, queryFn: () => assetsApi.wallets(), enabled })
}

export function useBountyTrustlines(bountyId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: qk.assets.bountyTrustlines(bountyId ?? ''),
    queryFn: () => assetsApi.bountyTrustlines(bountyId!),
    enabled: !!bountyId && enabled,
    staleTime: 20_000,
  })
}

export function useFundingReadiness(bountyId: string | undefined, address: string | null, enabled = true) {
  return useQuery({
    queryKey: qk.assets.fundingReadiness(bountyId ?? '', address ?? ''),
    queryFn: () => assetsApi.fundingReadiness(bountyId!, address!),
    enabled: !!bountyId && !!address && enabled,
    staleTime: 15_000,
  })
}

/** Everything a confirmed trustline or asset contract changes. */
export function invalidateAfterAssetOperation(client: QueryClient) {
  client.invalidateQueries({ queryKey: qk.assets.wallets })
  client.invalidateQueries({ queryKey: qk.assets.registry })
  client.invalidateQueries({ queryKey: qk.assets.admin })
  client.invalidateQueries({
    predicate: (q) =>
      q.queryKey[0] === 'bounties' &&
      (q.queryKey.includes('trustlines') || q.queryKey.includes('funding-readiness')),
  })
}

export function useAdminAssets() {
  return useQuery({ queryKey: qk.assets.admin, queryFn: () => adminAssetsApi.list() })
}

/** Every admin change refreshes both the staff list and the public registry the pickers read. */
function useAdminAssetMutation<TArg>(fn: (arg: TArg) => Promise<AdminRewardAsset>) {
  const client = useQueryClient()
  return useMutation<AdminRewardAsset, Error, TArg>({
    mutationFn: fn,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: qk.assets.admin })
      client.invalidateQueries({ queryKey: qk.assets.registry })
    },
  })
}

export function useCreateAsset() {
  return useAdminAssetMutation((body: CreateAssetRequest) => adminAssetsApi.create(body))
}

export function useUpdateAsset() {
  return useAdminAssetMutation(({ id, body }: { id: string; body: UpdateAssetRequest }) =>
    adminAssetsApi.update(id, body),
  )
}

export function useVerifyAsset() {
  return useAdminAssetMutation((id: string) => adminAssetsApi.verify(id))
}
