import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { walletsApi } from '../endpoints'
import type { WalletVerifyRequest } from '../types'
import { qk } from './keys'

export function useWallets(enabled = true) {
  return useQuery({ queryKey: qk.wallets.all, queryFn: () => walletsApi.list(), enabled })
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
    onSuccess: () => {
      client.invalidateQueries({ queryKey: qk.wallets.all })
      client.invalidateQueries({ queryKey: qk.auth.me })
      client.invalidateQueries({ queryKey: qk.users.all })
    },
  })
}

export function useRemoveWallet() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (walletId: string) => walletsApi.remove(walletId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: qk.wallets.all })
      client.invalidateQueries({ queryKey: qk.auth.me })
      client.invalidateQueries({ queryKey: qk.users.all })
    },
  })
}
