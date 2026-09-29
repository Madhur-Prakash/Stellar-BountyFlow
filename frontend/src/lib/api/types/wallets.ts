/** Wallet options, passkey smart wallets and fee sponsorship (backend `app/modules/wallets`). */
import type { DecimalString, ISODateTime, UserSummary } from '../types'

export type WalletOptions = {
  sponsorship: {
    enabled: boolean
    sponsor_address: string | null
    /** Contributor-side contract functions whose network fee BountyFlow pays. */
    functions: string[]
    daily_tx_limit: number
    used_today: number
  }
  passkey: {
    enabled: boolean
    unavailable_reason: string | null
    wasm_hash: string
    rpc_url: string
    network_passphrase: string
  }
}

export type PasskeyWalletStatus = 'DEPLOYING' | 'ACTIVE' | 'FAILED'

export type PasskeyWallet = {
  id: string
  contract_id: string
  key_id: string
  public_key: string
  network: string
  status: PasskeyWalletStatus
  wasm_hash: string
  deploy_tx_hash: string | null
  creation_ledger: number | null
  deployed_at: ISODateTime | null
  failure_reason: string | null
  explorer_url: string | null
  /** The address is linked as a verified wallet (SEP-45 proof done). */
  linked: boolean
  created_at: ISODateTime
}

export type PasskeyWalletCreateRequest = { key_id: string; public_key: string; deploy_xdr: string }

/** passkey-kit's WalletCandidateLookup (schema 2). */
export type PasskeyWalletCandidates = {
  schema: 2
  complete: true
  indexedThroughLedger: number
  candidates: {
    contractId: string
    birthWasmHash: string
    creationTransactionHash: string
    creationLedger: number
  }[]
}

export type SponsoredTransaction = {
  id: string
  kind: 'FEE_BUMP' | 'RELAY'
  purpose: string
  status: 'SUBMITTED' | 'CONFIRMED' | 'FAILED'
  user: UserSummary | null
  source_address: string | null
  envelope_hash: string
  inner_hash: string | null
  contract_id: string | null
  function_name: string | null
  max_fee: DecimalString | null
  fee_charged: DecimalString | null
  ledger_sequence: number | null
  failure_reason: string | null
  explorer_url: string | null
  created_at: ISODateTime
  confirmed_at: ISODateTime | null
}

export type SponsorshipOverview = {
  enabled: boolean
  sponsor_address: string | null
  balance: DecimalString | null
  low_balance: boolean
  stopped: boolean
  low_balance_threshold: DecimalString | null
  stop_threshold: DecimalString | null
  max_fee: DecimalString | null
  daily_tx_limit: number
  daily_fee_limit: DecimalString | null
  sponsored_today: number
  fees_today: DecimalString | null
  recent: SponsoredTransaction[]
}
