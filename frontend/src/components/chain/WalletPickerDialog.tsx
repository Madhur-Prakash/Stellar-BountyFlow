import { useQuery } from '@tanstack/react-query'
import { CircleAlert, ExternalLink, Fingerprint, LoaderCircle } from 'lucide-react'
import { Link } from 'react-router'

import { Bones } from '@/components/layout/Bones'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useMe } from '@/lib/api/queries/auth'
import { usePasskeyWallets, useWalletOptions } from '@/lib/api/queries/wallets'
import type { PasskeyWallet, WalletOptions } from '@/lib/api/types'
import { truncateMiddle } from '@/lib/stellar/explorer'
import { listWallets, PASSKEY_WALLET_ID, type WalletKind, type WalletOption } from '@/lib/stellar/wallet'
import { cn } from '@/lib/utils'
import { useWalletStore } from '@/stores/wallet'

const KIND_LABEL: Record<WalletKind, string> = {
  extension: 'Browser extension',
  web: 'Web wallet',
  passkey: 'Passkey',
  test: 'Test wallet',
}

/** A square monogram in place of third-party logos (no remote images, same look in both themes). */
export function WalletMark({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'flex size-9 shrink-0 items-center justify-center rounded-md border bg-surface font-display text-sm font-bold text-foreground',
        className,
      )}
    >
      {name
        .replace(/[^A-Za-z0-9]/g, '')
        .charAt(0)
        .toUpperCase() || '?'}
    </span>
  )
}

function Row({
  option,
  busy,
  disabled,
  onConnect,
}: {
  option: WalletOption
  busy: boolean
  disabled: boolean
  onConnect: () => void
}) {
  return (
    <li className="flex min-h-14 items-center gap-3 px-4 py-2.5">
      <WalletMark name={option.name} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{option.name}</p>
        <p className="text-xs text-muted-foreground">{KIND_LABEL[option.kind]}</p>
      </div>
      {option.available ? (
        <Button
          variant="outline"
          disabled={disabled}
          onClick={onConnect}
          aria-label={`Connect ${option.name}`}
        >
          {busy && <LoaderCircle className="animate-spin" aria-hidden />}
          Connect
        </Button>
      ) : option.url ? (
        <Button asChild variant="ghost">
          <a
            href={option.url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            aria-label={`Install ${option.name}`}
          >
            Install <ExternalLink aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        </Button>
      ) : (
        <Badge variant="muted">Not installed</Badge>
      )}
    </li>
  )
}

function RowsFallback() {
  return (
    <ul className="divide-y" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <li key={i} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
          <Skeleton className="size-9" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-28" />
            <Skeleton className="h-3 w-20" />
          </div>
          <Skeleton className="h-9 w-20" />
        </li>
      ))}
    </ul>
  )
}

function PasskeyRow({
  wallet,
  options,
  busy,
  disabled,
}: {
  wallet: PasskeyWallet
  options: WalletOptions
  busy: boolean
  disabled: boolean
}) {
  const choose = useWalletStore((s) => s.choose)
  return (
    <div className="flex min-h-14 items-center gap-3 rounded-lg border bg-card px-4 py-2.5">
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-primary/10 text-primary-emphasis"
      >
        <Fingerprint className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Passkey wallet</p>
        <p className="font-mono text-xs text-muted-foreground">{truncateMiddle(wallet.contract_id, 6, 6)}</p>
      </div>
      <Button
        disabled={disabled}
        onClick={() =>
          void choose(PASSKEY_WALLET_ID, {
            contractId: wallet.contract_id,
            keyId: wallet.key_id,
            rpcUrl: options.passkey.rpc_url,
            networkPassphrase: options.passkey.network_passphrase,
            walletWasmHash: wallet.wasm_hash,
          })
        }
      >
        {busy && <LoaderCircle className="animate-spin" aria-hidden />}
        Use
      </Button>
    </div>
  )
}

/** Wallet picker: installed and web wallets to connect, the others with an install link. */
export default function WalletPickerDialog() {
  const { pickerOpen, closePicker, choose, status, error, choosing } = useWalletStore()
  const { data: me } = useMe()
  const wallets = useQuery({
    queryKey: ['wallet-apps'],
    queryFn: listWallets,
    staleTime: 30_000,
    enabled: pickerOpen,
  })
  const { data: options } = useWalletOptions(!!me && pickerOpen)
  const { data: passkeys } = usePasskeyWallets(!!me && pickerOpen && !!options?.passkey.enabled)
  const passkey =
    passkeys?.find((w) => w.status === 'ACTIVE' && w.linked) ?? passkeys?.find((w) => w.status === 'ACTIVE')
  const connecting = status === 'connecting'
  const available = wallets.data?.filter((w) => w.available) ?? []
  const missing = wallets.data?.filter((w) => !w.available) ?? []

  return (
    <Dialog open={pickerOpen} onOpenChange={(open) => !open && closePicker()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] gap-4 overflow-y-auto sm:max-w-md">
        <DialogHeader className="pr-8">
          <DialogTitle className="text-base font-semibold">Connect a wallet</DialogTitle>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {options?.passkey.enabled &&
          (passkey ? (
            <PasskeyRow
              wallet={passkey}
              options={options}
              busy={connecting && choosing === PASSKEY_WALLET_ID}
              disabled={connecting}
            />
          ) : (
            <p className="text-[0.8125rem] text-muted-foreground">
              No wallet yet?{' '}
              <Link
                to="/app/profile#passkey"
                onClick={closePicker}
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                Create a passkey wallet
              </Link>{' '}
              that needs no extension and no XLM.
            </p>
          ))}

        <Bones name="wallet-picker" loading={wallets.isPending} fallback={<RowsFallback />}>
          {wallets.isError ? (
            <Alert variant="destructive">
              <CircleAlert />
              <AlertDescription>
                The wallet list could not be loaded. Close this and try again.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-4">
              {available.length > 0 && (
                <section aria-labelledby="wallets-available">
                  <h3 id="wallets-available" className="label-mono mb-1.5 text-[0.75rem]">
                    Available
                  </h3>
                  <ul className="divide-y overflow-hidden rounded-lg border">
                    {available.map((w) => (
                      <Row
                        key={w.id}
                        option={w}
                        busy={connecting && choosing === w.id}
                        disabled={connecting}
                        onConnect={() => void choose(w.id)}
                      />
                    ))}
                  </ul>
                </section>
              )}
              {missing.length > 0 && (
                <section aria-labelledby="wallets-missing">
                  <h3 id="wallets-missing" className="label-mono mb-1.5 text-[0.75rem]">
                    Not installed
                  </h3>
                  <ul className="divide-y overflow-hidden rounded-lg border">
                    {missing.map((w) => (
                      <Row key={w.id} option={w} busy={false} disabled onConnect={() => undefined} />
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </Bones>
      </DialogContent>
    </Dialog>
  )
}
