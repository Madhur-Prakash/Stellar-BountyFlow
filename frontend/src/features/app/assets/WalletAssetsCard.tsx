import { Coins } from 'lucide-react'

import { MonoValue } from '@/components/common/MonoValue'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useRewardAssets, useWalletAssets } from '@/lib/api/queries/assets'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { RewardAsset, TrustlineStatus, WalletAssets } from '@/lib/api/types'
import { formatMoney } from '@/lib/money'
import { accountExplorerUrl } from '@/lib/stellar/explorer'

import { CardQuery } from '../workspace-ui'
import { TrustlineBadge } from './TrustlineBadge'
import { TRUSTLINE_EXPLAINER } from './asset-display'
import { AddTrustlineButton, FaucetLink } from './TrustlineGuidance'

function AssetRow({
  line,
  entry,
  address,
}: {
  line: TrustlineStatus
  entry: RewardAsset | undefined
  address: string
}) {
  const code = line.asset.code
  return (
    <li className="flex flex-col gap-2 py-2.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{entry?.name ?? code}</span>
        <TrustlineBadge state={line.state} code={code} />
        {line.balance !== null && line.state === 'ACTIVE' && (
          <span className="amount text-sm text-muted-foreground">
            {formatMoney(line.balance, line.asset)}
          </span>
        )}
      </div>
      {entry && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {line.state === 'MISSING' && (
            <AddTrustlineButton asset={entry} address={address} variant="outline" />
          )}
          {line.state === 'ACTIVE' && <FaucetLink asset={entry}>Get test {code}</FaucetLink>}
        </div>
      )}
    </li>
  )
}

function WalletBlock({ wallet, registry }: { wallet: WalletAssets; registry: RewardAsset[] }) {
  const { data: config } = usePublicConfig()
  return (
    <li className="px-5 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <MonoValue
          value={wallet.address}
          label="wallet address"
          href={accountExplorerUrl(config, wallet.address)}
        />
        <span className="text-[0.8125rem] text-muted-foreground">
          {wallet.account_exists === false
            ? 'Not funded on the network yet'
            : wallet.native_spendable !== null
              ? `${formatMoney(wallet.native_spendable, 'XLM')} available`
              : wallet.account_exists === null
                ? 'Balance unavailable right now'
                : null}
        </span>
      </div>
      {wallet.trustlines.length > 0 && (
        <ul className="mt-1.5 divide-y">
          {wallet.trustlines.map((line) => (
            <AssetRow
              key={line.asset.identifier}
              line={line}
              entry={registry.find((r) => r.asset.identifier === line.asset.identifier)}
              address={wallet.address}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

/** Each verified wallet and whether it can receive every reward asset, with the trustline action. */
export function WalletAssetsCard() {
  const query = useWalletAssets()
  const { data: registry = [] } = useRewardAssets()
  return (
    <section id="assets" aria-labelledby="assets-h">
      <Card className="gap-0">
        <CardHeader className="pb-5">
          <CardTitle>
            <h2 id="assets-h">Assets and trustlines</h2>
          </CardTitle>
          <CardDescription>{TRUSTLINE_EXPLAINER}</CardDescription>
        </CardHeader>
        <div className="border-t">
          <CardQuery
            query={query}
            skeleton="app-profile-assets"
            rows={2}
            isEmpty={(d) => d.length === 0}
            empty={{
              icon: Coins,
              title: 'No verified wallet',
              description: 'Verify a wallet above to see which assets it can receive.',
            }}
          >
            {(wallets) => (
              <ul className="divide-y">
                {wallets.map((w) => (
                  <WalletBlock key={w.wallet_id} wallet={w} registry={registry} />
                ))}
              </ul>
            )}
          </CardQuery>
        </div>
      </Card>
    </section>
  )
}
