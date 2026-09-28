import { lazy, Suspense, type ReactNode } from 'react'

import { StatGrid, StatTile } from '@/components/common/StatTile'
import { QueryView } from '@/components/layout/QueryView'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { usePlatformAnalytics } from '@/lib/api/queries/analytics'
import type { PlatformAnalytics } from '@/lib/api/types'
import { formatDateTime, formatNumber, humanize } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

import { ChartCard, ChartEmpty, ChartFallback } from './workspace-ui'

const ActivityLineChart = lazy(() =>
  import('./analytics-charts').then((m) => ({ default: m.ActivityLineChart })),
)

const CHART_HEIGHT = 256

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

const SERIES = [
  { key: 'registrations', label: 'Registrations', color: 'var(--chart-1)' },
  { key: 'bounties_published', label: 'Bounties published', color: 'var(--chart-2)' },
  { key: 'applications', label: 'Applications', color: 'var(--chart-3)' },
  { key: 'submissions', label: 'Submissions', color: 'var(--chart-4)' },
] as const

type SeriesKey = (typeof SERIES)[number]['key']

function ActivityCard({ data }: { data: PlatformAnalytics['time_series'] }) {
  const rows = data.map((d) => ({ ...d, label: d.day.slice(5) }))
  const empty = rows.every((r) => SERIES.every((s) => r[s.key as SeriesKey] === 0))
  return (
    <ChartCard
      title="Last 30 days"
      description="Daily registrations, published bounties, applications and submissions (UTC)."
    >
      {empty ? (
        <ChartEmpty className="h-40 sm:h-64">No activity recorded in this window yet.</ChartEmpty>
      ) : (
        <Suspense fallback={<ChartFallback height={CHART_HEIGHT} />}>
          <ActivityLineChart rows={rows} series={[...SERIES]} height={CHART_HEIGHT} />
        </Suspense>
      )}
      <div className="sr-only">
        <table>
          <caption>Platform activity, last 30 days</caption>
          <thead>
            <tr>
              <th scope="col">Day</th>
              {SERIES.map((s) => (
                <th key={s.key} scope="col">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.day}>
                <th scope="row">{r.day}</th>
                {SERIES.map((s) => (
                  <td key={s.key}>{r[s.key as SeriesKey]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ChartCard>
  )
}

function Group({
  id,
  title,
  columns = 'min-[420px]:grid-cols-2 xl:grid-cols-4',
  children,
}: {
  id: string
  title: string
  columns?: string
  children: ReactNode
}) {
  return (
    <section aria-labelledby={`platform-${id}`}>
      <h3 id={`platform-${id}`} className="mb-2.5 text-[0.8125rem] font-medium text-muted-foreground">
        {title}
      </h3>
      <StatGrid className={cn('grid-cols-1', columns)}>{children}</StatGrid>
    </section>
  )
}

function PlatformContent({ data }: { data: PlatformAnalytics }) {
  const { users, bounties, transactions, engagement } = data
  return (
    <div className="space-y-6">
      <h2 className="sr-only">Platform</h2>
      <Group id="users" title="Users">
        <StatTile label="Registered users" value={formatNumber(users.registered_users)} />
        <StatTile
          label="Verified email"
          value={formatNumber(users.verified_users)}
          hint={`${pct(users.email_verification_rate)} of registered`}
        />
        <StatTile
          label="Connected wallets"
          value={formatNumber(users.connected_wallets)}
          hint={`${pct(users.wallet_connection_rate)} of registered`}
        />
        <StatTile label="Active in 30 days" value={formatNumber(users.active_users_30d)} />
      </Group>
      <Group id="bounties" title="Bounties">
        <StatTile label="Published" value={formatNumber(bounties.published_bounties)} />
        <StatTile label="Open" value={formatNumber(bounties.open_bounties)} />
        <StatTile label="Funded" value={formatNumber(bounties.funded_bounties)} />
        <StatTile label="Completed" value={formatNumber(bounties.completed_bounties)} />
      </Group>
      <Group id="transactions" title="On-chain">
        <StatTile
          label="Verified payout volume"
          value={
            <>
              {formatAmount(transactions.verified_payout_volume, { maxDecimals: 2 })}{' '}
              <span className="text-sm font-normal text-muted-foreground">XLM</span>
            </>
          }
        />
        <StatTile
          label="Successful transactions"
          value={formatNumber(transactions.successful_transactions)}
        />
        <StatTile label="Failed transactions" value={formatNumber(transactions.failed_transactions)} />
        <StatTile label="Transacting wallets" value={formatNumber(transactions.unique_transacting_wallets)} />
      </Group>
      <Group id="engagement" title="Engagement" columns="sm:grid-cols-3">
        <StatTile label="Repeat contributors" value={formatNumber(engagement.repeat_contributors)} />
        <StatTile
          label="Application acceptance"
          value={pct(engagement.application_acceptance_rate)}
          hint={`${formatNumber(engagement.applications_decided)} decided`}
        />
        <StatTile
          label="Submission approval"
          value={pct(engagement.submission_approval_rate)}
          hint={`${formatNumber(engagement.submissions_reviewed)} reviewed`}
        />
      </Group>
      <ActivityCard data={data.time_series} />
      {Object.keys(data.methodology).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              <h3>How these numbers are counted</h3>
            </CardTitle>
            <CardDescription>
              Generated{' '}
              <time dateTime={data.generated_at} className="tabular-nums">
                {formatDateTime(data.generated_at)}
              </time>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-8 gap-y-4 text-sm sm:grid-cols-2">
              {Object.entries(data.methodology).map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="font-medium">{humanize(k)}</dt>
                  <dd className="mt-0.5 text-muted-foreground">{v}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/** Platform-wide metrics for staff (permission analytics:platform). */
export function PlatformAnalyticsPanel() {
  const query = usePlatformAnalytics()
  return (
    <QueryView
      query={query}
      skeleton="app-analytics-platform"
      loading={<Skeleton className="h-96 rounded-xl" />}
      errorTitle="Platform analytics unavailable"
    >
      {(data) => <PlatformContent data={data} />}
    </QueryView>
  )
}
