import { http, seg } from '../client'
import type {
  PasskeyWallet,
  PasskeyWalletCandidates,
  PasskeyWalletCreateRequest,
  SponsorshipOverview,
  Wallet,
  WalletChallengeRequest,
  WalletChallengeResponse,
  WalletOptions,
  WalletVerifyRequest,
} from '../types'

export const walletsApi = {
  challenge: (body: WalletChallengeRequest) => http.post<WalletChallengeResponse>('/wallets/challenge', body),
  verify: (body: WalletVerifyRequest) => http.post<Wallet>('/wallets/verify', body),
  list: () => http.get<Wallet[]>('/wallets'),
  remove: (walletId: string) => http.delete<void>(`/wallets/${seg(walletId)}`),
  setPrimary: (walletId: string) => http.post<Wallet>(`/wallets/${seg(walletId)}/primary`, {}),
  options: () => http.get<WalletOptions>('/wallets/options'),
  passkeyList: () => http.get<PasskeyWallet[]>('/wallets/passkey'),
  passkeyCreate: (body: PasskeyWalletCreateRequest) => http.post<PasskeyWallet>('/wallets/passkey', body),
  passkeyCandidates: (keyId: string) =>
    http.get<PasskeyWalletCandidates>('/wallets/passkey/candidates', { key_id: keyId }),
  sponsorship: () => http.get<SponsorshipOverview>('/admin/sponsorship'),
}
