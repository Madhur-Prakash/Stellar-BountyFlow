import { format, isValid, parseISO } from 'date-fns'
import { lazy, Suspense } from 'react'

import { StatGrid, StatTile } from '@/components/common/StatTile'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMyAnalytics } from '@/lib/api/queries/analytics'
import { useMe } from '@/lib/api/queries/auth'
import type { MonthlyAmount } from '@/lib/api/types'
import { formatNumber, humanize } from '@/lib/format'
import { formatAmount, STROOPS_PER_UNIT, tryParseAmount } from '@/lib/money'
import { hasPermission } from '@/lib/permissions'

import { PlatformAnalyticsPanel } from './PlatformAnalyticsPanel'
import { ChartCard, ChartEmpty, ChartFallback } from './workspace-ui'

const MonthlyAmountChart = lazy(() =>
  import('./analytics-charts').then((m) => ({ default: m.MonthlyAmountChart })),
)
const StatusCountChart = lazy(() =>
  import('./analytics-charts').then((m) => ({ default: m.StatusCountChart })),
)

const MONTHLY_HEIGHT = 240
/** One 40px band per status; the chart sits at the top of its card. */
const statusHeight = (rows: number) => Math.max(rows * 40, 80)

/**
 * Charts need numbers. Amounts are converted from stroops (BigInt) only for plotting; every figure shown as
 * text uses the exact decimal string.
 */
function toChartNumber(amount: string): number {
  const stroops = tryParseAmount(amount) ?? 0n
  return Number(stroops) / Number(STROOPS_PER_UNIT)
}

/** "2026-09" → "Sep 26" */
function monthLabel(month: string): string {
  const d = parseISO(`${month}-01`)
  return isValid(d) ? format(d, 'MMM yy') : month
}

/** An XLM total at two decimals. */
function XlmFigure({ amount }: { amount: string }) {
  return (
    <>
      {formatAmount(amount, { maxDecimals: 2 })}{' '}
      <span className="text-sm font-normal text-muted-foreground">XLM</span>
    </>
  )
}

function MonthlyCard({
  title,
  description,
  data,
  empty,
  className,
}: {
  title: string
  description: string
  data: MonthlyAmount[]
  empty: string
  className?: string
}) {
  const rows = data.map((d) => ({
    label: monthLabel(d.month),
    amount: toChartNumber(d.amount),
    text: formatAmount(d.amount),
  }))
  const hasData = rows.some((r) => r.amount > 0)
  return (
    <ChartCard title={title} description={description} className={className}>
      {hasData ? (
        <>
          <Suspense fallback={<ChartFallback height={MONTHLY_HEIGHT} />}>
            <MonthlyAmountChart rows={rows} height={MONTHLY_HEIGHT} />
          </Suspense>
          <div className="sr-only">
            <table>
              <caption>{title}</caption>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.label}>
                    <th scope="row">{r.label}</th>
                    <td>{r.text} XLM</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <ChartEmpty className="h-32 sm:h-60">{empty}</ChartEmpty>
      )}
    </ChartCard>
  )
}

function StatusCard({
  title,
  counts,
  empty,
}: {
  title: string
  counts: Record<string, number>
  empty: string
}) {
  const rows = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([status, count]) => ({ status: humanize(status), count }))
  const total = rows.reduce((a, r) => a + r.count, 0)
  const height = statusHeight(rows.length)
  return (
    <ChartCard title={title} description={<span className="tabular-nums">{formatNumber(total)} total</span>}>
      {total === 0 ? (
        <ChartEmpty className="h-30">{empty}</ChartEmpty>
      ) : (
        <>
          <Suspense fallback={<ChartFallback height={height} />}>
            <StatusCountChart rows={rows} height={height} />
          </Suspense>
          <div className="sr-only">
            <table>
              <caption>{title}</caption>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.status}>
                    <th scope="row">{r.status}</th>
                    <td>{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </ChartCard>
  )
}

const sum = (counts: Record<string, number>) => Object.values(counts).reduce((a, n) => a + n, 0)

export default function AnalyticsPage() {
  const query = useMyAnalytics()
  const { data: me } = useMe()
  const staff = hasPermission(me, 'analytics:platform')
  return (
    <div>
      <PageHeader
        title="Analytics"
        description={
          staff
            ? 'Your own activity, plus platform-wide metrics for staff. Totals count confirmed payouts only.'
            : 'Your activity as a requester and as a contributor. Totals count confirmed payouts only.'
        }
      />
      <QueryView
        query={query}
        skeleton="app-analytics"
        loading={<Skeleton className="h-96 rounded-xl" />}
        errorTitle="Analytics unavailable"
      >
        {({ requester: r, contributor: c }) => (
          <Tabs defaultValue="requester" className="gap-0">
            <TabsList className="h-9">
              <TabsTrigger value="requester" className="px-3">
                Requester
              </TabsTrigger>
              <TabsTrigger value="contributor" className="px-3">
                Contributor
              </TabsTrigger>
              {staff && (
                <TabsTrigger value="platform" className="px-3">
                  Platform
                </TabsTrigger>
              )}
            </TabsList>

            <TabsContent value="requester" className="mt-5 space-y-6">
              <h2 className="sr-only">As a requester</h2>
              <StatGrid className="grid-cols-2 xl:grid-cols-4">
                <StatTile label="Total escrowed" value={<XlmFigure amount={r.total_escrowed} />} />
                <StatTile label="Total paid" value={<XlmFigure amount={r.total_paid} />} />
                <StatTile label="Applications received" value={formatNumber(r.applications_received)} />
                <StatTile
                  label="First application"
                  value={
                    r.avg_time_to_first_application_hours === null
                      ? '—'
                      : `${r.avg_time_to_first_application_hours.toFixed(1)} h`
                  }
                  hint="Average time after publishing"
                />
              </StatGrid>
              <div className="grid gap-6 lg:grid-cols-2">
                <MonthlyCard
                  title="Spending by month"
                  description="Confirmed payouts you released"
                  data={r.spending_by_month}
                  empty="No payouts released yet."
                />
                <StatusCard
                  title="Bounties by status"
                  counts={r.bounties_by_status}
                  empty="No bounties yet."
                />
              </div>
            </TabsContent>

            <TabsContent value="contributor" className="mt-5 space-y-6">
              <h2 className="sr-only">As a contributor</h2>
              <StatGrid className="grid-cols-2 xl:grid-cols-4">
                <StatTile label="Total earned" value={<XlmFigure amount={c.total_earned} />} />
                <StatTile label="Completed bounties" value={formatNumber(c.completed_count)} />
                <StatTile label="Applications sent" value={formatNumber(sum(c.applications_by_status))} />
                <StatTile label="Submissions" value={formatNumber(sum(c.submissions_by_status))} />
              </StatGrid>
              <MonthlyCard
                title="Earnings by month"
                description="Confirmed payouts received"
                data={c.earnings_by_month}
                empty="Earnings appear after your first approved submission is paid out."
              />
              <div className="grid gap-6 lg:grid-cols-2">
                <StatusCard
                  title="Applications by status"
                  counts={c.applications_by_status}
                  empty="No applications yet."
                />
                <StatusCard
                  title="Submissions by status"
                  counts={c.submissions_by_status}
                  empty="No submissions yet."
                />
              </div>
            </TabsContent>

            {staff && (
              <TabsContent value="platform" className="mt-5">
                <PlatformAnalyticsPanel />
              </TabsContent>
            )}
          </Tabs>
        )}
      </QueryView>
    </div>
  )
}
