import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { walletsApi } from '../endpoints'
import type { PasskeyWallet, WalletVerifyRequest } from '../types'
import { qk } from './keys'

/** Everything that changes when a wallet is linked, unlinked or made the payout wallet. */
export function invalidateWallets(client: QueryClient) {
  return Promise.all([
    client.invalidateQueries({ queryKey: qk.wallets.all }),
    client.invalidateQueries({ queryKey: qk.auth.me }),
    client.invalidateQueries({ queryKey: qk.users.all }),
  ])
}

export function useWallets(enabled = true) {
  return useQuery({ queryKey: qk.wallets.all, queryFn: () => walletsApi.list(), enabled })
}

/** Fee sponsorship and passkey availability on this server. */
export function useWalletOptions(enabled = true) {
  return useQuery({
    queryKey: qk.wallets.options,
    queryFn: () => walletsApi.options(),
    enabled,
    staleTime: 60_000,
  })
}

const deploying = (wallets: PasskeyWallet[] | undefined) => wallets?.some((w) => w.status === 'DEPLOYING')

/** The user's passkey smart wallets; polls while a deployment is being confirmed. */
export function usePasskeyWallets(enabled = true) {
  return useQuery({
    queryKey: qk.wallets.passkey,
    queryFn: () => walletsApi.passkeyList(),
    enabled,
    refetchInterval: (query) => (deploying(query.state.data) ? 3000 : false),
  })
}

export function useWalletChallenge() {
  return useMutation({
    mutationFn: (publicAddress: string) => walletsApi.challenge({ public_address: publicAddress }),
  })
}

export function useVerifyWallet() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: WalletVerifyRequest) => walletsApi.verify(body),
    onSuccess: () => invalidateWallets(client),
  })
}

export function useRemoveWallet() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (walletId: string) => walletsApi.remove(walletId),
    onSuccess: () => invalidateWallets(client),
  })
}

export function useSetPrimaryWallet() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (walletId: string) => walletsApi.setPrimary(walletId),
    onSuccess: () => invalidateWallets(client),
  })
}

/** Staff: sponsor balance and recent sponsored transactions. */
export function useSponsorshipOverview(enabled = true) {
  return useQuery({
    queryKey: qk.admin.sponsorship,
    queryFn: () => walletsApi.sponsorship(),
    enabled,
    refetchInterval: 30_000,
  })
}
