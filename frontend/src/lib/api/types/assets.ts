/**
 * Reward assets: the registry (XLM, USDC and other Stellar Asset Contract tokens), trustline status and
 * guidance, and the wallet-signed trustline / asset-contract operations (docs/api.md, "Assets"). Re-exported
 * from `../types`.
 */
import type { Asset, DecimalString, ISODateTime, UserSummary } from '../types'

/** An enabled reward asset a bounty can pay in. */
export type RewardAsset = {
  id: string
  asset: Asset
  name: string
  is_default: boolean
  /** Classic assets (USDC…) need a trustline on G-addresses before they can be received. */
  requires_trustline: boolean
  /** Where to get test units (Circle's faucet for Testnet USDC). */
  faucet_url: string | null
}

export type ContractStatus = 'DEPLOYED' | 'NOT_DEPLOYED'

export type AdminRewardAsset = RewardAsset & {
  is_enabled: boolean
  contract_status: ContractStatus
  symbol: string | null
  decimals: number
  issuer_flags: Record<string, boolean>
  sort_order: number
  bounty_count: number
  verified_at: ISODateTime | null
  created_by: UserSummary | null
  created_at: ISODateTime
  updated_at: ISODateTime
}

/** Either `code` + `issuer`, or `contract_id` of the asset's Stellar Asset Contract. */
export type CreateAssetRequest = {
  code?: string
  issuer?: string
  contract_id?: string
  name?: string
  enable?: boolean
}

export type UpdateAssetRequest = { is_enabled?: boolean; name?: string; sort_order?: number }

export const TRUSTLINE_STATES = [
  'NOT_REQUIRED',
  'ACTIVE',
  'MISSING',
  'UNAUTHORIZED',
  'ACCOUNT_MISSING',
  'NO_WALLET',
  'UNKNOWN',
] as const
export type TrustlineState = (typeof TRUSTLINE_STATES)[number]

export type TrustlineStatus = {
  asset: Asset
  address: string | null
  state: TrustlineState
  balance: DecimalString | null
}

export type WalletAssets = {
  wallet_id: string
  address: string
  network: string
  /** null when Horizon could not be reached. */
  account_exists: boolean | null
  native_balance: DecimalString | null
  /** XLM after the account's reserve and open offers. */
  native_spendable: DecimalString | null
  trustlines: TrustlineStatus[]
}

export type ApplicantTrustline = { contributor_id: string; address: string | null; state: TrustlineState }

export type BountyTrustlines = {
  asset: Asset
  requires_trustline: boolean
  applicants: ApplicantTrustline[]
}

export type FundingReadiness = {
  asset: Asset
  address: string
  /** What the next deposit needs (the remaining escrow amount). */
  required: DecimalString
  available: DecimalString | null
  trustline: TrustlineState
  ready: boolean
  message: string | null
  faucet_url: string | null
}

export type AssetOperationKind = 'TRUSTLINE' | 'DEPLOY_CONTRACT'
export type AssetOperationStatus = 'SIGNATURE_REQUIRED' | 'SUBMITTED' | 'CONFIRMED' | 'FAILED' | 'EXPIRED'

export type AssetOperation = {
  id: string
  kind: AssetOperationKind
  status: AssetOperationStatus
  asset: Asset
  network: string
  source_address: string
  transaction_hash: string
  ledger_sequence: number | null
  submitted_at: ISODateTime | null
  confirmed_at: ISODateTime | null
  failure_reason: string | null
  explorer_url: string | null
  created_at: ISODateTime
}

export type PreparedAssetOperation = {
  operation: AssetOperation
  unsigned_xdr: string
  network_passphrase: string
  network: string
  description: string
  fee_estimate_stroops: string | null
  expires_at: ISODateTime
}
