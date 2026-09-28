import { Info } from 'lucide-react'
import { Link } from 'react-router'

import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageContainer } from '@/components/layout/PageContainer'
import { CountUp } from '@/components/motion/CountUp'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { usePublicStats } from '@/lib/api/queries/analytics'
import type { PublicStats } from '@/lib/api/types'
import { formatDateTime, formatNumber, humanize } from '@/lib/format'
import { formatAmount, isZeroAmount } from '@/lib/money'
import { networkDisplayName } from '@/lib/stellar/explorer'

import { SectionHeading } from './SectionHeading'

type StatKey = keyof Pick<
  PublicStats,
  | 'published_bounties'
  | 'open_bounties'
  | 'funded_bounties'
  | 'completed_bounties'
  | 'registered_users'
  | 'successful_transactions'
  | 'unique_transacting_wallets'
>

const COUNTS: { key: StatKey; label: string }[] = [
  { key: 'published_bounties', label: 'Bounties published' },
  { key: 'open_bounties', label: 'Open right now' },
  { key: 'funded_bounties', label: 'Funded in escrow' },
  { key: 'completed_bounties', label: 'Completed' },
  { key: 'registered_users', label: 'Registered users' },
  { key: 'successful_transactions', label: 'Confirmed transactions' },
  { key: 'unique_transacting_wallets', label: 'Transacting wallets' },
]

function Methodology({ methodology }: { methodology: Record<string, string> }) {
  const entries = Object.entries(methodology)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="text-muted-foreground">
          <Info /> How we count
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 text-sm">
        <h3 className="font-medium">Methodology</h3>
        {entries.length === 0 ? (
          <p className="mt-2 text-muted-foreground">
            The API did not provide a methodology for these figures.
          </p>
        ) : (
          <dl className="mt-2 max-h-72 space-y-2 overflow-y-auto" data-lenis-prevent>
            {entries.map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs font-medium">{humanize(k)}</dt>
                <dd className="text-xs text-muted-foreground">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </PopoverContent>
    </Popover>
  )
}

function StatsFallback() {
  return (
    <div className="grid grid-cols-2 gap-8 lg:grid-cols-5" aria-hidden>
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i}>
          <Skeleton className="h-12 w-24" />
          <Skeleton className="mt-2 h-4 w-28" />
        </div>
      ))}
    </div>
  )
}

const PRIMARY: { key: StatKey; label: string }[] = [
  { key: 'open_bounties', label: 'Open right now' },
  { key: 'funded_bounties', label: 'Funded in escrow' },
  { key: 'completed_bounties', label: 'Completed' },
  { key: 'registered_users', label: 'People signed up' },
]

/** Real platform numbers from GET /analytics/public. Zeros are shown as zeros. */
export function PlatformStats() {
  const { data, isPending, isError, error, refetch } = usePublicStats()

  const allZero =
    !!data && COUNTS.every(({ key }) => data[key] === 0) && isZeroAmount(data.verified_payout_volume || '0')

  return (
    <section aria-labelledby="stats-title" className="border-b bg-surface py-16 sm:py-20">
      <PageContainer>
        <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-end sm:justify-between">
          <SectionHeading
            id="stats-title"
            title="Activity so far"
            description="Live figures from the API. Payout volume counts only payouts confirmed on-chain."
          />
          {data && <Methodology methodology={data.methodology} />}
        </div>

        <div className="mt-12" aria-live="polite">
          {isError ? (
            <ErrorState error={error} title="Statistics are unavailable" onRetry={() => refetch()} />
          ) : (
            <Bones name="platform-stats" loading={isPending} fallback={<StatsFallback />}>
              {data && (
                <>
                  <dl className="grid grid-cols-2 gap-x-8 gap-y-8 lg:grid-cols-5 lg:divide-x lg:divide-border">
                    <div className="col-span-2 lg:col-span-1 lg:pr-8">
                      <dd className="amount text-[3rem] leading-none sm:text-[3.5rem]">
                        <CountUp
                          value={Number(data.verified_payout_volume) || 0}
                          format={(n) => formatAmount(n.toFixed(2), { maxDecimals: 2 })}
                          display={formatAmount(data.verified_payout_volume, { maxDecimals: 2 })}
                        />
                        <span
                          className="ml-1.5 text-lg font-normal text-muted-foreground"
                          style={{ fontStretch: '100%' }}
                        >
                          XLM
                        </span>
                      </dd>
                      <dt className="mt-2 text-sm text-muted-foreground">Verified payout volume</dt>
                    </div>
                    {PRIMARY.map(({ key, label }) => (
                      <div key={key} className="lg:px-8">
                        <dd className="amount text-[3rem] leading-none sm:text-[3.5rem]">
                          <CountUp value={data[key]} />
                        </dd>
                        <dt className="mt-2 text-sm text-muted-foreground">{label}</dt>
                      </div>
                    ))}
                  </dl>

                  <p className="mt-8 text-sm text-muted-foreground">
                    Network: {networkDisplayName(data.network)}. {formatNumber(data.successful_transactions)}{' '}
                    confirmed transactions from {formatNumber(data.unique_transacting_wallets)} wallets.
                    Updated <time dateTime={data.generated_at}>{formatDateTime(data.generated_at)}</time>.
                  </p>

                  {allZero && (
                    <div className="mt-8 flex flex-col items-start gap-3 border-t pt-6 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-[0.9375rem]">
                        Nothing has settled on this network yet. The first funded bounty starts every number
                        above.
                      </p>
                      <Button asChild>
                        <Link to="/app/bounties/create">Post the first bounty</Link>
                      </Button>
                    </div>
                  )}
                </>
              )}
            </Bones>
          )}
        </div>
      </PageContainer>
    </section>
  )
}
