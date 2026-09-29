import { CircleAlert, ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { assetsApi } from '@/lib/api/endpoints'
import type { Asset, AssetOperation, RewardAsset, TrustlineState } from '@/lib/api/types'

import { TRUSTLINE_EXPLAINER, useRegistryAsset } from './asset-display'
import { AssetOperationButton } from './AssetOperationDialog'

/** "Add USDC trustline": builds the changeTrust for `address`, the wallet signs, the API confirms it. */
export function AddTrustlineButton({
  asset,
  address,
  onConfirmed,
  size = 'sm',
  variant = 'default',
}: {
  asset: RewardAsset
  address: string
  onConfirmed?: (op: AssetOperation) => void
  size?: 'sm' | 'default'
  variant?: 'default' | 'outline'
}) {
  const code = asset.asset.code
  return (
    <AssetOperationButton
      label={`Add ${code} trustline`}
      title={`Add ${code} trustline`}
      description={TRUSTLINE_EXPLAINER}
      confirmedToast={`${code} trustline added`}
      size={size}
      variant={variant}
      prepare={() => assetsApi.prepareTrustline(asset.id, address)}
      onConfirmed={onConfirmed}
    />
  )
}

export function FaucetLink({ asset, children }: { asset: RewardAsset; children?: ReactNode }) {
  if (!asset.faucet_url) return null
  return (
    <a
      href={asset.faucet_url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="inline-flex min-h-9 items-center gap-1.5 text-sm font-medium text-primary-emphasis hover:underline"
    >
      {children ?? `Get test ${asset.asset.code} from Circle`}{' '}
      <ExternalLink className="size-3.5" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  )
}

/**
 * What to do when a wallet can't use an asset yet: a short explanation, the "Add … trustline" action (for the
 * signed-in user's own G-address) and, on Testnet, where to get test units.
 */
export function TrustlineGuidance({
  asset,
  address,
  state,
  title,
  message,
  canAct = true,
}: {
  asset: Asset
  address: string | null
  state: TrustlineState
  title?: string
  message?: string | null
  /** The address belongs to the viewer, so they can add the trustline themselves. */
  canAct?: boolean
}) {
  const entry = useRegistryAsset(asset)
  const code = asset.code
  const missing = state === 'MISSING'
  return (
    <Alert variant="warning" data-testid="trustline-guidance">
      <CircleAlert />
      <AlertTitle>
        {title ?? (missing ? `Add a ${code} trustline` : `This wallet can't use ${code} yet`)}
      </AlertTitle>
      <AlertDescription className="space-y-2">
        {message && <p className="text-foreground">{message}</p>}
        {missing && <p>{TRUSTLINE_EXPLAINER}</p>}
        {state === 'UNAUTHORIZED' && (
          <p>
            The {code} issuer must authorize this wallet before it can hold {code}.
          </p>
        )}
        {state === 'ACCOUNT_MISSING' && <p>Fund the account with XLM first (on Testnet, use Friendbot).</p>}
        {entry && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1">
            {missing && canAct && address && !address.startsWith('C') && (
              <AddTrustlineButton asset={entry} address={address} />
            )}
            <FaucetLink asset={entry} />
          </div>
        )}
      </AlertDescription>
    </Alert>
  )
}
