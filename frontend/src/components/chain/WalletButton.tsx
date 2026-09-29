import {
  ArrowLeftRight,
  ChevronDown,
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  LogOut,
  RefreshCw,
  ShieldCheck,
  Wallet,
} from 'lucide-react'
import { useEffect } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useMe } from '@/lib/api/queries/auth'
import { usePublicConfig } from '@/lib/api/queries/config'
import { useWallets } from '@/lib/api/queries/wallets'
import { accountExplorerUrl, contractExplorerUrl, truncateMiddle } from '@/lib/stellar/explorer'
import { networkLabelFromPassphrase } from '@/lib/stellar/wallet'
import { cn } from '@/lib/utils'
import { useWalletStore } from '@/stores/wallet'

import { useVerifyOwnership } from './useVerifyOwnership'

/** Header / onboarding wallet control: choose a wallet, verify ownership, check the network. */
export function WalletButton({ className }: { className?: string }) {
  const { status, address, network, walletName, detect, openPicker, disconnect, refreshNetwork } =
    useWalletStore()
  const { data: config } = usePublicConfig()
  const { data: me } = useMe()
  const { data: wallets } = useWallets(!!me)
  const { verify, pending } = useVerifyOwnership()

  useEffect(() => {
    if (status === 'unknown') void detect()
  }, [status, detect])

  const expectedPassphrase = config?.network_passphrase
  const wrongNetwork =
    !!network?.networkPassphrase && !!expectedPassphrase && network.networkPassphrase !== expectedPassphrase
  const linked = address ? wallets?.find((w) => w.public_address === address) : undefined
  const isContract = !!address?.startsWith('C')

  if (!address) {
    const busy = status === 'unknown' || status === 'connecting'
    return (
      <Button variant="outline" className={className} disabled={busy} aria-busy={busy} onClick={openPicker}>
        {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : <Wallet aria-hidden />}
        {status === 'unknown' ? 'Checking wallet…' : 'Connect wallet'}
      </Button>
    )
  }

  const walletNetwork = network?.networkPassphrase
    ? networkLabelFromPassphrase(network.networkPassphrase)
    : networkLabelFromPassphrase(expectedPassphrase)
  const explorerHref = isContract ? contractExplorerUrl(config, address) : accountExplorerUrl(config, address)

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
            <span>{walletName ?? 'Wallet'}</span>
            <span className={cn(wrongNetwork && 'font-medium text-warning')}>{walletNetwork}</span>
          </div>
          <div className="font-mono text-xs break-all text-foreground">{address}</div>
        </DropdownMenuLabel>
        {wrongNetwork && (
          <div className="mx-2 mb-1.5 rounded-md border border-warning/30 bg-warning/5 px-2.5 py-2 text-xs">
            <p className="font-medium text-warning">Wrong network</p>
            <p className="mt-0.5 text-muted-foreground">
              Switch {walletName ?? 'your wallet'} to {networkLabelFromPassphrase(expectedPassphrase)}.
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
        <DropdownMenuItem onSelect={openPicker}>
          <ArrowLeftRight /> Switch wallet
        </DropdownMenuItem>
        {!isContract && (
          <DropdownMenuItem onSelect={() => void refreshNetwork()}>
            <RefreshCw /> Refresh network
          </DropdownMenuItem>
        )}
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
