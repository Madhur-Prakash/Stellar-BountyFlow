import { CircleAlert, Fuel } from 'lucide-react'

import { MonoValue } from '@/components/common/MonoValue'
import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { usePublicConfig } from '@/lib/api/queries/config'
import { useSponsorshipOverview } from '@/lib/api/queries/wallets'
import type { SponsoredTransaction, SponsorshipOverview } from '@/lib/api/types'
import { formatRelative, humanize } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { accountExplorerUrl } from '@/lib/stellar/explorer'

const STATUS_VARIANT = {
  CONFIRMED: 'success',
  SUBMITTED: 'info',
  FAILED: 'danger',
} as const

function Figure({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="px-4 py-3">
      <p className="label-mono text-[0.7rem]">{label}</p>
      <p className="amount mt-0.5 text-[0.9375rem]">{children}</p>
    </div>
  )
}

function Row({ tx }: { tx: SponsoredTransaction }) {
  return (
    <li className="flex items-center justify-between gap-3 px-4 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-[0.8125rem] font-medium">{humanize(tx.purpose)}</span>
          <Badge variant={STATUS_VARIANT[tx.status]}>{humanize(tx.status)}</Badge>
        </div>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {tx.user ? `@${tx.user.username}` : 'No account'}
          {tx.function_name ? ` · ${tx.function_name}` : ''} · {formatRelative(tx.created_at)}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="amount text-[0.8125rem]">
          {formatAmount(tx.fee_charged ?? tx.max_fee ?? '0')}{' '}
          <span className="text-muted-foreground">XLM</span>
        </p>
        {tx.explorer_url && (
          <a
            href={tx.explorer_url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="font-mono text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            {tx.envelope_hash.slice(0, 8)}…<span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </div>
    </li>
  )
}

function Content({ data }: { data: SponsorshipOverview }) {
  const { data: config } = usePublicConfig()
  if (!data.enabled) {
    return (
      <p className="px-4 py-5 text-sm text-muted-foreground">
        Fee sponsorship is off: no sponsor key is configured on this server (STELLAR_SPONSOR_SECRET).
      </p>
    )
  }
  return (
    <div>
      {(data.stopped || data.low_balance) && (
        <div className="px-4 pt-4">
          <Alert variant={data.stopped ? 'destructive' : 'warning'}>
            <CircleAlert />
            <AlertTitle>{data.stopped ? 'Sponsorship stopped' : 'Sponsor balance is low'}</AlertTitle>
            <AlertDescription>
              {data.stopped
                ? `The sponsor holds less than ${formatAmount(data.stop_threshold ?? '0')} XLM, so no fees are being paid. Top it up to resume.`
                : `The sponsor holds less than ${formatAmount(data.low_balance_threshold ?? '0')} XLM. Top it up before it runs out.`}
            </AlertDescription>
          </Alert>
        </div>
      )}
      <div className="grid grid-cols-2 divide-x divide-y border-b sm:grid-cols-4 sm:divide-y-0">
        <Figure label="Balance">
          {formatAmount(data.balance ?? '0')} <span className="text-muted-foreground">XLM</span>
        </Figure>
        <Figure label="Fees today">
          {formatAmount(data.fees_today ?? '0')} <span className="text-muted-foreground">XLM</span>
        </Figure>
        <Figure label="Sponsored today">{data.sponsored_today}</Figure>
        <Figure label="Daily cap per user">{data.daily_tx_limit}</Figure>
      </div>
      {data.sponsor_address && (
        <div className="border-b px-4 py-2.5">
          <MonoValue
            value={data.sponsor_address}
            label="sponsor address"
            href={accountExplorerUrl(config, data.sponsor_address)}
          />
        </div>
      )}
      {data.recent.length === 0 ? (
        <p className="px-4 py-5 text-sm text-muted-foreground">No sponsored transactions yet.</p>
      ) : (
        <ul className="divide-y">
          {data.recent.map((tx) => (
            <Row key={tx.id} tx={tx} />
          ))}
        </ul>
      )}
    </div>
  )
}

function Fallback() {
  return (
    <div role="status" aria-label="Loading" className="space-y-px p-4">
      <Skeleton className="h-16 w-full rounded-lg" />
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-12 w-full rounded-none" />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  )
}

/** Staff card: the fee sponsor's balance, today's spend and the last sponsored transactions. */
export function SponsorshipCard() {
  const query = useSponsorshipOverview()
  return (
    <Card className="gap-0 overflow-hidden pb-0">
      <CardHeader className="pb-5">
        <CardTitle className="flex items-center gap-2">
          <Fuel className="size-4 text-muted-foreground" aria-hidden />
          <h2>Fee sponsorship</h2>
        </CardTitle>
        <CardDescription>Network fees BountyFlow pays for contributors and smart wallets.</CardDescription>
      </CardHeader>
      <div className="border-t">
        {query.isError ? (
          <div className="p-4">
            <ErrorState
              error={query.error}
              title="Could not load sponsorship"
              onRetry={() => void query.refetch()}
            />
          </div>
        ) : (
          <Bones name="admin-sponsorship" loading={query.isPending} fallback={<Fallback />}>
            {query.data ? <Content data={query.data} /> : null}
          </Bones>
        )}
      </div>
    </Card>
  )
}
