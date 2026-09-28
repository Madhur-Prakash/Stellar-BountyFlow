import type { BlockchainMode, BlockchainTransaction, PublicConfig } from '@/lib/api/types'

/**
 * Builds block-explorer links from `/config/public.explorer_base_url`
 * (e.g. "https://stellar.expert/explorer/testnet"). The base URL already
 * encodes the network, so links always match the API's active network.
 */
export type ExplorerConfig = Pick<PublicConfig, 'explorer_base_url' | 'blockchain_mode' | 'network'>

export type ExplorerKind = 'tx' | 'account' | 'contract'

/** Transaction states in which nothing was ever sent to the network. */
export const NOT_SUBMITTED: ReadonlySet<BlockchainTransaction['status']> = new Set([
  'CREATED',
  'SIGNATURE_REQUIRED',
  'EXPIRED',
])

const SAFE_ID = /^[A-Za-z0-9]+$/

export function explorerUrl(
  config: ExplorerConfig | null | undefined,
  kind: ExplorerKind,
  id: string | null | undefined,
): string | null {
  if (!config || !id) return null
  const base = (config.explorer_base_url || '').replace(/\/+$/, '')
  if (!/^https:\/\//i.test(base)) return null
  if (!SAFE_ID.test(id)) return null
  return `${base}/${kind}/${id}`
}

export const txExplorerUrl = (c: ExplorerConfig | null | undefined, hash: string | null | undefined) =>
  explorerUrl(c, 'tx', hash)
export const accountExplorerUrl = (
  c: ExplorerConfig | null | undefined,
  address: string | null | undefined,
) => explorerUrl(c, 'account', address)
export const contractExplorerUrl = (
  c: ExplorerConfig | null | undefined,
  contractId: string | null | undefined,
) => explorerUrl(c, 'contract', contractId)

/** Display label for a network string or blockchain mode. */
export function networkDisplayName(network: string | null | undefined, mode?: BlockchainMode | null): string {
  const n = (network ?? '').toLowerCase()
  if (n.includes('test')) return 'Testnet'
  if (n.includes('main') || n.includes('public') || n === 'pubnet') return 'Mainnet'
  if (n.includes('future')) return 'Futurenet'
  if (mode === 'testnet') return 'Testnet'
  if (mode === 'mainnet') return 'Mainnet'
  return network || 'Unknown'
}

/** GABC…WXYZ style truncation for addresses, hashes, and contract ids. */
export function truncateMiddle(value: string | null | undefined, lead = 6, tail = 6): string {
  if (!value) return '—'
  if (value.length <= lead + tail + 1) return value
  return `${value.slice(0, lead)}…${value.slice(-tail)}`
}

/**
 * Explorer link for a transaction that reached the network. Prefers the
 * API-provided `explorer_url`. Prepared-but-unsigned (CREATED /
 * SIGNATURE_REQUIRED) and EXPIRED transactions were never submitted, so their
 * hash does not exist on-chain and gets no link.
 */
export function transactionExplorerHref(
  tx: Pick<BlockchainTransaction, 'transaction_hash' | 'explorer_url'> &
    Partial<Pick<BlockchainTransaction, 'status'>>,
  config: ExplorerConfig | null | undefined,
): string | null {
  if (!tx.transaction_hash) return null
  if (tx.status && NOT_SUBMITTED.has(tx.status)) return null
  if (tx.explorer_url && /^https:\/\//i.test(tx.explorer_url)) return tx.explorer_url
  return txExplorerUrl(config, tx.transaction_hash)
}
