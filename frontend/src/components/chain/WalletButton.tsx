import { useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  LogOut,
  RefreshCw,
  ShieldCheck,
  Wallet,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { errorMessage } from '@/lib/api/client'
import { walletsApi } from '@/lib/api/endpoints'
import { useMe } from '@/lib/api/queries/auth'
import { usePublicConfig } from '@/lib/api/queries/config'
import { qk } from '@/lib/api/queries/keys'
import { useWallets } from '@/lib/api/queries/wallets'
import { accountExplorerUrl, truncateMiddle } from '@/lib/stellar/explorer'
import {
  FREIGHTER_INSTALL_URL,
  networkLabelFromPassphrase,
  signTransaction,
  walletErrorMessage,
} from '@/lib/stellar/wallet'
import { cn } from '@/lib/utils'
import { useWalletStore } from '@/stores/wallet'

/**
 * Proves wallet ownership: POST /wallets/challenge → sign the SEP-10-style
 * challenge in the wallet (never submitted) → POST /wallets/verify.
 */
function useVerifyOwnership() {
  const client = useQueryClient()
  const [pending, setPending] = useState(false)
  const verify = async (address: string) => {
    if (pending) return false
    setPending(true)
    try {
      const challenge = await walletsApi.challenge({ public_address: address })
      const signed = await signTransaction(challenge.challenge_xdr, {
        networkPassphrase: challenge.network_passphrase,
        address,
      })
      await walletsApi.verify({ public_address: address, signed_challenge_xdr: signed })
      toast.success('Wallet ownership verified by signature')
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.wallets.all }),
        client.invalidateQueries({ queryKey: qk.auth.me }),
        client.invalidateQueries({ queryKey: qk.users.all }),
      ])
      return true
    } catch (e) {
      toast.error(e instanceof Error && e.name === 'WalletError' ? walletErrorMessage(e) : errorMessage(e))
      return false
    } finally {
      setPending(false)
    }
  }
  return { verify, pending }
}

function FreighterWalletButton({ className }: { className?: string }) {
  const { status, address, network, error, detect, connect, disconnect, refreshNetwork } = useWalletStore()
  const { data: config } = usePublicConfig()
  const { data: me } = useMe()
  const { data: wallets } = useWallets(!!me)
  const { verify, pending } = useVerifyOwnership()

  useEffect(() => {
    if (status === 'unknown') void detect()
  }, [status, detect])

  const expectedPassphrase = config?.network_passphrase
  const wrongNetwork = !!network && !!expectedPassphrase && network.networkPassphrase !== expectedPassphrase
  const linked = address ? wallets?.find((w) => w.public_address === address) : undefined

  if (status === 'not_installed') {
    return (
      <Button asChild variant="outline" className={className}>
        <a href={FREIGHTER_INSTALL_URL} target="_blank" rel="noopener noreferrer nofollow">
          <Wallet aria-hidden /> Install Freighter
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      </Button>
    )
  }

  if (!address) {
    const detecting = status === 'unknown'
    return (
      <Button
        variant="outline"
        className={className}
        disabled={status === 'connecting' || detecting}
        aria-busy={detecting || status === 'connecting'}
        onClick={async () => {
          const a = await connect()
          if (!a && useWalletStore.getState().error) toast.error(useWalletStore.getState().error!)
        }}
        title={error ?? undefined}
      >
        {status === 'connecting' || detecting ? (
          <LoaderCircle className="animate-spin" aria-hidden />
        ) : (
          <Wallet aria-hidden />
        )}
        {detecting ? 'Checking wallet…' : 'Connect wallet'}
      </Button>
    )
  }

  const walletNetwork = network ? networkLabelFromPassphrase(network.networkPassphrase) : 'Unknown network'
  const explorerHref = accountExplorerUrl(config, address)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={cn('gap-2 pr-2.5', className)}
          aria-label={wrongNetwork ? 'Wallet menu, wrong network' : 'Wallet menu'}
        >
          <Wallet className={wrongNetwork ? 'text-warning' : 'text-muted-foreground'} aria-hidden />
          <span className="font-mono text-[0.8125rem]">{truncateMiddle(address, 4, 4)}</span>
          {wrongNetwork && <CircleAlert className="text-warning" aria-hidden />}
          <ChevronDown className="text-muted-foreground" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="space-y-1 font-normal">
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Freighter</span>
            <span className={cn(wrongNetwork && 'font-medium text-warning')}>{walletNetwork}</span>
          </div>
          <div className="font-mono text-xs break-all text-foreground">{address}</div>
        </DropdownMenuLabel>
        {wrongNetwork && (
          <div className="mx-2 mb-1.5 rounded-md border border-warning/30 bg-warning/5 px-2.5 py-2 text-xs">
            <p className="font-medium text-warning">Wrong network</p>
            <p className="mt-0.5 text-muted-foreground">
              Switch Freighter to {networkLabelFromPassphrase(expectedPassphrase)}.
            </p>
          </div>
        )}
        <DropdownMenuSeparator />
        {linked ? (
          <DropdownMenuItem disabled>
            <ShieldCheck className="text-success" /> Verified for your account
          </DropdownMenuItem>
        ) : me ? (
          <DropdownMenuItem disabled={pending} onSelect={() => void verify(address)}>
            {pending ? <LoaderCircle className="animate-spin" /> : <ShieldCheck />} Verify ownership
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem onSelect={() => void refreshNetwork()}>
          <RefreshCw /> Refresh network
        </DropdownMenuItem>
        {explorerHref && (
          <DropdownMenuItem asChild>
            <a href={explorerHref} target="_blank" rel="noopener noreferrer nofollow">
              <ExternalLink /> View on explorer
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={disconnect}>
          <LogOut /> Disconnect
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Header / onboarding wallet control: connect, verify ownership, check the network. */
export function WalletButton({ className }: { className?: string }) {
  return <FreighterWalletButton className={className} />
}
