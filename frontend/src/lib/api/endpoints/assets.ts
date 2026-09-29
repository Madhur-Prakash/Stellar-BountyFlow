import { http, seg } from '../client'
import type {
  AdminRewardAsset,
  AssetOperation,
  BountyTrustlines,
  CreateAssetRequest,
  FundingReadiness,
  PreparedAssetOperation,
  RewardAsset,
  UpdateAssetRequest,
  WalletAssets,
} from '../types'

export const assetsApi = {
  /** Enabled reward assets on this network (public). */
  list: () => http.get<RewardAsset[]>('/assets'),
  /** The signed-in user's verified wallets and whether each can receive every reward asset. */
  wallets: () => http.get<WalletAssets[]>('/assets/wallets'),
  prepareTrustline: (assetId: string, walletAddress: string) =>
    http.post<PreparedAssetOperation>(`/assets/${seg(assetId)}/trustline/prepare`, {
      wallet_address: walletAddress,
    }),
  submitOperation: (operationId: string, signedXdr: string) =>
    http.post<AssetOperation>(`/assets/operations/${seg(operationId)}/submit`, { signed_xdr: signedXdr }),
  getOperation: (operationId: string) => http.get<AssetOperation>(`/assets/operations/${seg(operationId)}`),
  /** Requester only: can each applicant's payout wallet receive the bounty's asset? */
  bountyTrustlines: (bountyId: string) => http.get<BountyTrustlines>(`/bounties/${seg(bountyId)}/trustlines`),
  fundingReadiness: (bountyId: string, walletAddress: string) =>
    http.get<FundingReadiness>(`/bounties/${seg(bountyId)}/funding/readiness`, {
      wallet_address: walletAddress,
    }),
}

export const adminAssetsApi = {
  list: () => http.get<AdminRewardAsset[]>('/admin/assets'),
  create: (body: CreateAssetRequest) => http.post<AdminRewardAsset>('/admin/assets', body),
  update: (assetId: string, body: UpdateAssetRequest) =>
    http.patch<AdminRewardAsset>(`/admin/assets/${seg(assetId)}`, body),
  verify: (assetId: string) => http.post<AdminRewardAsset>(`/admin/assets/${seg(assetId)}/verify`),
  prepareDeploy: (assetId: string, walletAddress: string) =>
    http.post<PreparedAssetOperation>(`/admin/assets/${seg(assetId)}/deploy/prepare`, {
      wallet_address: walletAddress,
    }),
}
