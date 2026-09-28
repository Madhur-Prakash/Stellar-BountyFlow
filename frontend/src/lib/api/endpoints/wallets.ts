import { http, seg } from '../client'
import type { Wallet, WalletChallengeRequest, WalletChallengeResponse, WalletVerifyRequest } from '../types'

export const walletsApi = {
  challenge: (body: WalletChallengeRequest) => http.post<WalletChallengeResponse>('/wallets/challenge', body),
  verify: (body: WalletVerifyRequest) => http.post<Wallet>('/wallets/verify', body),
  list: () => http.get<Wallet[]>('/wallets'),
  remove: (walletId: string) => http.delete<void>(`/wallets/${seg(walletId)}`),
}
