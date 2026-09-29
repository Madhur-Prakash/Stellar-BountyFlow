import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, ExternalLink, Fingerprint, LoaderCircle, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useVerifyOwnership } from '@/components/chain/useVerifyOwnership'
import { MonoValue } from '@/components/common/MonoValue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { errorMessage } from '@/lib/api/client'
import { walletsApi } from '@/lib/api/endpoints'
import { useMe } from '@/lib/api/queries/auth'
import { usePublicConfig } from '@/lib/api/queries/config'
import { qk } from '@/lib/api/queries/keys'
import { usePasskeyWallets, useWalletOptions } from '@/lib/api/queries/wallets'
import type { PasskeyWallet, WalletOptions } from '@/lib/api/types'
import { contractExplorerUrl } from '@/lib/stellar/explorer'
import { loadPasskeyKit, PASSKEY_WALLET_ID, walletErrorMessage } from '@/lib/stellar/wallet'
import { useWalletStore } from '@/stores/wallet'

import { CardQuery } from '../workspace-ui'

function StatusBadge({ wallet }: { wallet: PasskeyWallet }) {
  if (wallet.status === 'ACTIVE')
    return (
      <Badge variant={wallet.linked ? 'success' : 'info'}>
        {wallet.linked ? <ShieldCheck aria-hidden /> : <Fingerprint aria-hidden />}
        {wallet.linked ? 'Ownership verified by signature' : 'Created, not verified yet'}
      </Badge>
    )
  if (wallet.status === 'DEPLOYING')
    return (
      <Badge variant="warning">
        <LoaderCircle className="animate-spin" aria-hidden /> Deploying
      </Badge>
    )
  return (
    <Badge variant="danger">
      <CircleAlert aria-hidden /> Failed
    </Badge>
  )
}

function passkeyConfig(options: WalletOptions, wasmHash?: string) {
  return {
    rpcUrl: options.passkey.rpc_url,
    networkPassphrase: options.passkey.network_passphrase,
    walletWasmHash: wasmHash ?? options.passkey.wasm_hash,
  }
}

/**
 * Passkey smart wallets: a Soroban wallet contract whose only signer is a WebAuthn passkey on this device. The
 * platform sponsor deploys and pays for it, so the wallet needs no XLM of its own.
 */
export function PasskeyWalletCard() {
  const { data: me } = useMe()
  const { data: config } = usePublicConfig()
  const { data: options } = useWalletOptions(!!me)
  const query = usePasskeyWallets(!!me && !!options?.passkey.enabled)
  const client = useQueryClient()
  const { verify, pending: verifying } = useVerifyOwnership()
  const [creating, setCreating] = useState(false)
  const choose = useWalletStore((s) => s.choose)

  const create = async () => {
    if (!options || creating) return
    setCreating(true)
    try {
      const { createPasskeyWallet, confirmPasskeyWallet } = await loadPasskeyKit()
      const cfg = passkeyConfig(options)
      const created = await createPasskeyWallet(cfg, me?.username ?? 'BountyFlow')
      const wallet = await walletsApi.passkeyCreate({
        key_id: created.keyId,
        public_key: created.publicKey,
        deploy_xdr: created.deployXdr,
      })
      if (wallet.deploy_tx_hash) {
        // Records the verified wallet birth locally, so the passkey reconnects on this device without a lookup.
        await confirmPasskeyWallet(cfg, created.created, wallet.deploy_tx_hash).catch(() => undefined)
      }
      await client.invalidateQueries({ queryKey: qk.wallets.passkey })
      toast.success('Passkey wallet created')
    } catch (e) {
      toast.error(e instanceof Error && e.name === 'WalletError' ? walletErrorMessage(e) : errorMessage(e))
    } finally {
      setCreating(false)
    }
  }

  if (!options?.passkey.enabled) {
    return (
      <section id="passkey" aria-labelledby="passkey-h">
        <Card className="gap-0">
          <CardHeader className="pb-5">
            <CardTitle>
              <h2 id="passkey-h">Passkey wallet</h2>
            </CardTitle>
            <CardDescription>
              {options?.passkey.unavailable_reason ??
                'A Stellar smart wallet secured by a passkey, with no browser extension to install.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </section>
    )
  }

  return (
    <section id="passkey" aria-labelledby="passkey-h">
      <Card className="gap-0">
        <CardHeader className="pb-5">
          <CardTitle>
            <h2 id="passkey-h">Passkey wallet</h2>
          </CardTitle>
          <CardDescription>
            A Stellar smart wallet whose only signer is a passkey on your device. BountyFlow pays its network
            fees, so it needs no XLM to receive or fund a bounty.
          </CardDescription>
        </CardHeader>
        <div className="border-t">
          <CardQuery
            query={query}
            skeleton="app-profile-passkey"
            rows={1}
            isEmpty={(d) => d.length === 0}
            empty={{
              icon: Fingerprint,
              title: 'No passkey wallet yet',
              description: 'Creating one asks for a passkey, then deploys its wallet contract on Stellar.',
            }}
          >
            {(wallets) => (
              <ul className="divide-y">
                {wallets.map((w) => (
                  <li
                    key={w.id}
                    className="flex flex-col gap-2 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0 space-y-1.5">
                      <MonoValue
                        value={w.contract_id}
                        label="wallet address"
                        href={contractExplorerUrl(config, w.contract_id)}
                      />
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <StatusBadge wallet={w} />
                        {w.failure_reason && <span>{w.failure_reason}</span>}
                        {w.explorer_url && (
                          <a
                            href={w.explorer_url}
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                            className="inline-flex items-center gap-1 underline-offset-4 hover:underline"
                          >
                            Deployment <ExternalLink className="size-3" aria-hidden />
                            <span className="sr-only">(opens in a new tab)</span>
                          </a>
                        )}
                      </div>
                    </div>
                    {w.status === 'ACTIVE' && (
                      <div className="flex items-center gap-1 self-start sm:self-center">
                        {!w.linked && options && (
                          <Button
                            size="sm"
                            disabled={verifying}
                            onClick={() =>
                              void verify(w.contract_id, {
                                contractId: w.contract_id,
                                keyId: w.key_id,
                                ...passkeyConfig(options, w.wasm_hash),
                              })
                            }
                          >
                            {verifying ? <LoaderCircle className="animate-spin" /> : <ShieldCheck />} Verify
                            ownership
                          </Button>
                        )}
                        {w.linked && options && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              void choose(PASSKEY_WALLET_ID, {
                                contractId: w.contract_id,
                                keyId: w.key_id,
                                ...passkeyConfig(options, w.wasm_hash),
                              })
                            }
                          >
                            <Fingerprint /> Use this wallet
                          </Button>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardQuery>
        </div>
        <CardContent className="hidden" />
        <CardFooter className="px-5 py-3">
          <Button variant="outline" disabled={creating} onClick={() => void create()}>
            {creating ? <LoaderCircle className="animate-spin" aria-hidden /> : <Fingerprint aria-hidden />}
            Create a passkey wallet
          </Button>
        </CardFooter>
      </Card>
    </section>
  )
}
