import { BadgeCheck, Fingerprint, ShieldCheck, Star, Trash2, Wallet } from 'lucide-react'
import { toast } from 'sonner'

import { WalletButton } from '@/components/chain/WalletButton'
import { MonoValue } from '@/components/common/MonoValue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { errorMessage } from '@/lib/api/client'
import { usePublicConfig } from '@/lib/api/queries/config'
import { useRemoveWallet, useSetPrimaryWallet, useWallets } from '@/lib/api/queries/wallets'
import type { Wallet as LinkedWallet, WalletProofMethod } from '@/lib/api/types'
import { formatDate } from '@/lib/format'
import { accountExplorerUrl, contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'

import { CardQuery } from '../workspace-ui'

/** Wallet apps BountyFlow records a proof for; anything else is shown as sent by the wallet. */
const WALLET_APPS: Record<string, string> = {
  freighter: 'Freighter',
  xbull: 'xBull',
  albedo: 'Albedo',
  lobstr: 'LOBSTR',
  hana: 'Hana Wallet',
  rabet: 'Rabet',
  klever: 'Klever Wallet',
  onekey: 'OneKey Wallet',
  BitgetWallet: 'Bitget Wallet',
  cactuslink: 'Cactus Link',
  dcent: "D'CENT Wallet",
  scopuly: 'Scopuly',
  fordefi: 'Fordefi',
  ghostsig: 'GHOSTSIG',
  passkey: 'Passkey wallet',
  'smart-wallet': 'Smart wallet',
  'bountyflow-test': 'Test wallet',
}

const PROOFS: Record<WalletProofMethod, string> = {
  sep10: 'Signed challenge transaction',
  sep53: 'Signed message',
  sep45: 'Authorized by the smart wallet',
}

function walletAppName(wallet: LinkedWallet): string | null {
  if (!wallet.wallet_app) return wallet.proof_method === 'sep45' ? 'Smart wallet' : null
  return WALLET_APPS[wallet.wallet_app] ?? wallet.wallet_app
}

/** Linked wallets: which app proved each one, how, and which one payouts go to. */
export function LinkedWalletsCard() {
  const query = useWallets()
  const remove = useRemoveWallet()
  const setPrimary = useSetPrimaryWallet()
  const { data: config } = usePublicConfig()

  return (
    <section id="wallets" aria-labelledby="wallets-h">
      <Card className="gap-0">
        <CardHeader className="pb-5">
          <CardTitle>
            <h2 id="wallets-h">Linked wallets</h2>
          </CardTitle>
          <CardDescription>
            Payouts go only to a wallet you’ve verified. Verifying signs a one-time proof; nothing is
            submitted to the network.
          </CardDescription>
        </CardHeader>
        <div className="border-t">
          <CardQuery
            query={query}
            skeleton="app-profile-wallets"
            rows={1}
            isEmpty={(d) => d.length === 0}
            empty={{
              icon: Wallet,
              title: 'No wallets linked',
              description: 'Connect a wallet, then choose “Verify ownership” in the wallet menu.',
            }}
          >
            {(wallets) => {
              const payout = wallets.find((w) => w.is_primary) ?? wallets[0]
              return (
                <ul className="divide-y">
                  {wallets.map((w) => {
                    const contract = w.kind === 'contract' || w.public_address.startsWith('C')
                    const app = walletAppName(w)
                    return (
                      <li
                        key={w.id}
                        className="flex flex-col gap-2 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div className="min-w-0 space-y-1.5">
                          <MonoValue
                            value={w.public_address}
                            label="wallet address"
                            href={
                              contract
                                ? contractExplorerUrl(config, w.public_address)
                                : accountExplorerUrl(config, w.public_address)
                            }
                          />
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <Badge variant="success">
                              <ShieldCheck aria-hidden /> Ownership verified by signature
                            </Badge>
                            {app && (
                              <Badge variant="muted">
                                {contract ? <Fingerprint aria-hidden /> : <Wallet aria-hidden />} {app}
                              </Badge>
                            )}
                            {w.id === payout?.id && (
                              <Badge variant="info">
                                <BadgeCheck aria-hidden /> Payout wallet
                              </Badge>
                            )}
                            {w.proof_method && <span>{PROOFS[w.proof_method]}.</span>}
                            <span>
                              {networkDisplayName(w.network)}, verified {formatDate(w.verified_at)}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 self-start sm:self-center">
                          {w.id !== payout?.id && (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={setPrimary.isPending}
                              onClick={() =>
                                setPrimary.mutate(w.id, {
                                  onSuccess: () => toast.success('Payouts now go to this wallet'),
                                  onError: (e) => toast.error(errorMessage(e)),
                                })
                              }
                            >
                              <Star /> Use for payouts
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive hover:text-destructive"
                            disabled={remove.isPending}
                            onClick={() =>
                              remove.mutate(w.id, {
                                onSuccess: () => toast.success('Wallet unlinked'),
                                onError: (e) => toast.error(errorMessage(e)),
                              })
                            }
                          >
                            <Trash2 /> Unlink
                          </Button>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )
            }}
          </CardQuery>
        </div>
        <CardFooter className="px-5 py-3">
          <WalletButton />
        </CardFooter>
      </Card>
    </section>
  )
}
