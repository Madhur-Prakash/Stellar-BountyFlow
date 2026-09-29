/**
 * Shared, non-component helpers for reward assets: labels, the registry lookup and what a trustline is.
 * Kept out of the component files so fast refresh keeps working for them.
 */
import { useRewardAssets } from '@/lib/api/queries/assets'
import type { Asset, RewardAsset } from '@/lib/api/types'
import { shortAddress } from '@/lib/money'

/** Identifier of the native asset (XLM). */
export const NATIVE = 'native'

/** One sentence, shown wherever a trustline is asked for. */
export const TRUSTLINE_EXPLAINER =
  'A trustline lets a Stellar account hold an asset other than XLM; adding one sets aside 0.5 XLM as a reserve.'

/** "USDC" alone, or with its issuer when another enabled asset shares the code. */
export function rewardAssetLabel(entry: RewardAsset, all: RewardAsset[]): string {
  const code = entry.asset.code
  const shared = all.filter((a) => a.asset.code === code).length > 1
  const issuer = shared && entry.asset.issuer ? ` (${shortAddress(entry.asset.issuer)})` : ''
  return `${code}${issuer}`
}

/** The code of a reward asset identifier ("native" → XLM), from the registry. */
export function useAssetCode(identifier: string | null | undefined): string {
  const { data } = useRewardAssets()
  if (!identifier || identifier === NATIVE) return 'XLM'
  return data?.find((a) => a.asset.identifier === identifier)?.asset.code ?? identifier.split(':')[0] ?? 'XLM'
}

/** The registry entry for an asset (for its id, name and faucet). */
export function useRegistryAsset(asset: Pick<Asset, 'identifier'> | null | undefined): RewardAsset | null {
  const { data } = useRewardAssets()
  if (!asset) return null
  return data?.find((a) => a.asset.identifier === asset.identifier) ?? null
}
