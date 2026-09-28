import { Info } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { usePublicStats } from '@/lib/api/queries/analytics'
import type { PublicStats } from '@/lib/api/types'
import { formatDateTime, formatNumber, humanize } from '@/lib/format'
import { formatAmount, isZeroAmount } from '@/lib/money'
import { networkDisplayName } from '@/lib/stellar/explorer'
import { cn } from '@/lib/utils'

import { SectionHeading } from './SectionHeading'

type CountKey = keyof Pick<
  PublicStats,
  | 'published_bounties'
  | 'open_bounties'
  | 'funded_bounties'
  | 'completed_bounties'
  | 'registered_users'
  | 'successful_transactions'
  | 'unique_transacting_wallets'
>

const COUNTS: CountKey[] = [
  'published_bounties',
  'open_bounties',
  'funded_bounties',
  'completed_bounties',
  'registered_users',
  'successful_transactions',
  'unique_transacting_wallets',
]

const SHOWN: { key: CountKey; label: string }[] = [
  { key: 'open_bounties', label: 'Open right now' },
  { key: 'funded_bounties', label: 'Funded in escrow' },
  { key: 'completed_bounties', label: 'Completed' },
  { key: 'registered_users', label: 'Members' },
]

function Methodology({ methodology }: { methodology: Record<string, string> }) {
  const entries = Object.entries(methodology)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="pill" className="text-muted-foreground hover:text-foreground">
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

/** One figure in the grid: a label on top and the number set large and light below it. */
function Figure({ label, value, className }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'flex min-h-40 flex-col justify-between gap-8 bg-card px-5 py-6 sm:px-7 sm:py-7',
        className,
      )}
    >
      <dt className="text-[0.9375rem] text-muted-foreground">{label}</dt>
      <dd className="font-display text-[2.25rem] leading-none tabular-nums sm:text-[2.75rem]">{value}</dd>
    </div>
  )
}

function Figures({ data }: { data?: PublicStats }) {
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border bg-border lg:grid-cols-5">
      <Figure
        className="col-span-2 lg:col-span-1"
        label="Verified payout volume"
        value={
          data ? (
            <>
              {formatAmount(data.verified_payout_volume, { maxDecimals: 2 })}
              <span className="ml-2 text-base tracking-normal text-muted-foreground">XLM</span>
            </>
          ) : (
            '—'
          )
        }
      />
      {SHOWN.map(({ key, label }) => (
        <Figure key={key} label={label} value={data ? formatNumber(data[key]) : '—'} />
      ))}
    </dl>
  )
}

/** Real platform numbers from GET /analytics/public, in a hairline grid. Zeros are shown as zeros. */
export function PlatformStats() {
  const { data, isPending, isError, error, refetch } = usePublicStats()
  const allZero =
    !!data && COUNTS.every((key) => data[key] === 0) && isZeroAmount(data.verified_payout_volume || '0')

  return (
    <section aria-labelledby="stats-title" className="py-16 sm:py-20">
      <PageContainer>
        <SectionHeading
          id="stats-title"
          label="Live figures"
          title="Activity on BountyFlow"
          description="Payouts are counted once they are confirmed on Stellar."
          actions={data && <Methodology methodology={data.methodology} />}
        />
        <div className="mt-10" aria-live="polite">
          {isError ? (
            <ErrorState error={error} title="Statistics are unavailable" onRetry={() => refetch()} />
          ) : (
            <Bones name="platform-stats" loading={isPending} fallback={<Figures />}>
              {data && (
                <>
                  <Figures data={data} />
                  <p className="mt-4 text-sm text-muted-foreground">
                    Stellar {networkDisplayName(data.network)}. {formatNumber(data.successful_transactions)}{' '}
                    confirmed transactions from {formatNumber(data.unique_transacting_wallets)} wallets.
                    Updated <time dateTime={data.generated_at}>{formatDateTime(data.generated_at)}</time>.
                  </p>
                  {allZero && (
                    <div className="mt-6 flex flex-col items-start gap-3 rounded-2xl border bg-card p-6 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-[0.9375rem]">
                        Nothing has settled on this network yet. The first funded bounty starts every number
                        above.
                      </p>
                      <Button asChild variant="inverse" size="pill">
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
