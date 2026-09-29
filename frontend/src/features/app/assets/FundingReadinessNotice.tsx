import { useFundingReadiness } from '@/lib/api/queries/assets'
import type { BountyDetail } from '@/lib/api/types'
import { useWalletStore } from '@/stores/wallet'

import { TrustlineGuidance } from './TrustlineGuidance'

/**
 * Before funding: whether the connected wallet holds the escrow asset with enough balance. Shown only when it
 * doesn't, with the trustline action and (on Testnet) where to get test units.
 */
export function FundingReadinessNotice({ bounty, className }: { bounty: BountyDetail; className?: string }) {
  const address = useWalletStore((s) => s.address)
  const { data } = useFundingReadiness(bounty.id, address, bounty.reward_asset.type !== 'native')
  if (!data || data.ready || !data.message || !address) return null
  return (
    <div className={className}>
      <TrustlineGuidance
        asset={data.asset}
        address={address}
        state={data.trustline}
        title={
          data.trustline === 'MISSING'
            ? `Add a ${data.asset.code} trustline to fund this bounty`
            : `Not enough ${data.asset.code} to fund this bounty`
        }
        message={data.message}
      />
    </div>
  )
}
