import { Info } from 'lucide-react'
import { Link } from 'react-router'

import { StatGrid, StatTile } from '@/components/common/StatTile'
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

function Tiles({ data }: { data?: PublicStats }) {
  return (
    <StatGrid className="grid-cols-2 lg:grid-cols-5">
      <StatTile
        className="col-span-2 lg:col-span-1"
        label="Verified payout volume"
        value={
          data ? (
            <>
              {formatAmount(data.verified_payout_volume, { maxDecimals: 2 })}{' '}
              <span className="text-sm font-normal text-muted-foreground">XLM</span>
            </>
          ) : (
            '—'
          )
        }
      />
      {SHOWN.map(({ key, label }) => (
        <StatTile key={key} label={label} value={data ? formatNumber(data[key]) : '—'} />
      ))}
    </StatGrid>
  )
}

/** Real platform numbers from GET /analytics/public. Zeros are shown as zeros. */
export function PlatformStats() {
  const { data, isPending, isError, error, refetch } = usePublicStats()
  const allZero =
    !!data && COUNTS.every((key) => data[key] === 0) && isZeroAmount(data.verified_payout_volume || '0')

  return (
    <section aria-labelledby="stats-title" className="py-12 sm:py-14">
      <PageContainer>
        <SectionHeading
          id="stats-title"
          title="Activity on BountyFlow"
          description="Payouts are counted once they are confirmed on Stellar."
          actions={data && <Methodology methodology={data.methodology} />}
        />
        <div className="mt-6" aria-live="polite">
          {isError ? (
            <ErrorState error={error} title="Statistics are unavailable" onRetry={() => refetch()} />
          ) : (
            <Bones name="platform-stats" loading={isPending} fallback={<Tiles />}>
              {data && (
                <>
                  <Tiles data={data} />
                  <p className="mt-3 text-xs text-muted-foreground">
                    Stellar {networkDisplayName(data.network)}. {formatNumber(data.successful_transactions)}{' '}
                    confirmed transactions from {formatNumber(data.unique_transacting_wallets)} wallets.
                    Updated <time dateTime={data.generated_at}>{formatDateTime(data.generated_at)}</time>.
                  </p>
                  {allZero && (
                    <div className="mt-6 flex flex-col items-start gap-3 rounded-xl border bg-card p-5 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-sm">
                        Nothing has settled on this network yet. The first funded bounty starts every number
                        above.
                      </p>
                      <Button asChild size="sm">
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
