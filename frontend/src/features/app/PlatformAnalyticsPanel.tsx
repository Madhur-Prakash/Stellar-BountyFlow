import { Info } from 'lucide-react'
import type { ReactNode } from 'react'
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts'

import { StatTile } from '@/components/common/StatTile'
import { QueryView } from '@/components/layout/QueryView'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import { usePlatformAnalytics } from '@/lib/api/queries/analytics'
import type { PlatformAnalytics } from '@/lib/api/types'
import { formatDateTime, formatNumber, humanize } from '@/lib/format'
import { formatAmount } from '@/lib/money'

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

const activityConfig = {
  registrations: { label: 'Registrations', color: 'var(--chart-1)' },
  bounties_published: { label: 'Bounties published', color: 'var(--chart-2)' },
  applications: { label: 'Applications', color: 'var(--chart-3)' },
  submissions: { label: 'Submissions', color: 'var(--chart-4)' },
} satisfies ChartConfig

type SeriesKey = keyof typeof activityConfig
const SERIES = Object.keys(activityConfig) as SeriesKey[]

function ActivityChart({ data }: { data: PlatformAnalytics['time_series'] }) {
  const rows = data.map((d) => ({ ...d, label: d.day.slice(5) }))
  const empty = rows.every((r) => SERIES.every((k) => r[k] === 0))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Last 30 days</CardTitle>
        <CardDescription>
          Daily registrations, published bounties, applications and submissions (UTC).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {empty ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No activity recorded in this window yet.
          </p>
        ) : (
          <ChartContainer config={activityConfig} className="h-64 w-full">
            <LineChart data={rows} accessibilityLayer margin={{ left: 4, right: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} />
              <YAxis tickLine={false} axisLine={false} width={32} allowDecimals={false} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              {SERIES.map((k) => (
                <Line
                  key={k}
                  type="monotone"
                  dataKey={k}
                  stroke={`var(--color-${k})`}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          </ChartContainer>
        )}
        <table className="sr-only">
          <caption>Platform activity, last 30 days</caption>
          <thead>
            <tr>
              <th scope="col">Day</th>
              {SERIES.map((k) => (
                <th key={k} scope="col">
                  {activityConfig[k].label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.day}>
                <th scope="row">{r.day}</th>
                {SERIES.map((k) => (
                  <td key={k}>{r[k]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function Group({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`platform-${id}`}>
      <h3 id={`platform-${id}`} className="mb-3 text-sm font-semibold">
        {title}
      </h3>
      <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-4">
        {children}
      </div>
    </section>
  )
}

function PlatformContent({ data }: { data: PlatformAnalytics }) {
  const { users, bounties, transactions, engagement } = data
  return (
    <div className="space-y-8">
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
        <StatTile
          label="Transacting wallets"
          value={formatNumber(transactions.unique_transacting_wallets)}
        />
      </Group>
      <Group id="engagement" title="Engagement">
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
      <ActivityChart data={data.time_series} />
      {Object.keys(data.methodology).length > 0 && (
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Info className="size-4 text-muted-foreground" aria-hidden /> How these numbers are counted
            </CardTitle>
            <CardDescription>
              Generated{' '}
              <time dateTime={data.generated_at} className="tabular-nums">
                {formatDateTime(data.generated_at)}
              </time>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
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
