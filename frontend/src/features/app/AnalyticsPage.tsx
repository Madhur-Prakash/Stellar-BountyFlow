import {
  ChartNoAxesCombined,
  CircleDollarSign,
  Clock3,
  FileCheck2,
  GitPullRequest,
  Wallet,
} from 'lucide-react'
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'

import { StatTile } from '@/components/common/StatTile'
import { EmptyState } from '@/components/layout/EmptyState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMyAnalytics } from '@/lib/api/queries/analytics'
import { useMe } from '@/lib/api/queries/auth'
import type { MonthlyAmount } from '@/lib/api/types'
import { formatNumber, humanize } from '@/lib/format'
import { formatAmount, tryParseAmount, STROOPS_PER_UNIT } from '@/lib/money'
import { hasPermission } from '@/lib/permissions'

import { PlatformAnalyticsPanel } from './PlatformAnalyticsPanel'

/**
 * Charts need numbers. Amounts are converted from stroops (BigInt) only for
 * plotting and count-up frames; every figure shown as text uses the exact decimal string.
 */
function toChartNumber(amount: string): number {
  const stroops = tryParseAmount(amount) ?? 0n
  return Number(stroops) / Number(STROOPS_PER_UNIT)
}

/** An XLM total that counts up on first view and settles on the exact two-decimal amount. */
function XlmFigure({ amount }: { amount: string }) {
  return (
    <>
      {formatAmount(amount, { maxDecimals: 2 })}{' '}
      <span className="text-sm font-normal text-muted-foreground">XLM</span>
    </>
  )
}

const moneyConfig = { amount: { label: 'XLM', color: 'var(--chart-1)' } } satisfies ChartConfig
const countConfig = { count: { label: 'Count', color: 'var(--chart-2)' } } satisfies ChartConfig

function MonthlyChart({
  title,
  description,
  data,
}: {
  title: string
  description: string
  data: MonthlyAmount[]
}) {
  const rows = data.map((d) => ({
    month: d.month,
    amount: toChartNumber(d.amount),
    label: formatAmount(d.amount),
  }))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">No data yet.</p>
        ) : (
          <ChartContainer config={moneyConfig} className="h-64 w-full">
            <BarChart data={rows} accessibilityLayer>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="month" tickLine={false} axisLine={false} tickMargin={8} />
              <YAxis tickLine={false} axisLine={false} width={56} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar dataKey="amount" fill="var(--color-amount)" radius={4} />
            </BarChart>
          </ChartContainer>
        )}
        {rows.length > 0 && (
          <table className="sr-only">
            <caption>{title}</caption>
            <tbody>
              {rows.map((r) => (
                <tr key={r.month}>
                  <th scope="row">{r.month}</th>
                  <td>{r.label} XLM</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}

function StatusChart({ title, counts }: { title: string; counts: Record<string, number> }) {
  const rows = Object.entries(counts).map(([status, count]) => ({ status: humanize(status), count }))
  const total = rows.reduce((a, r) => a + r.count, 0)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription className="tabular-nums">{formatNumber(total)} total</CardDescription>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Nothing yet.</p>
        ) : (
          <ChartContainer config={countConfig} className="h-56 w-full">
            <BarChart data={rows} layout="vertical" accessibilityLayer margin={{ left: 8 }}>
              <XAxis type="number" hide allowDecimals={false} />
              <YAxis type="category" dataKey="status" tickLine={false} axisLine={false} width={120} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar dataKey="count" fill="var(--color-count)" radius={4} />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}

export default function AnalyticsPage() {
  const query = useMyAnalytics()
  const { data: me } = useMe()
  const staff = hasPermission(me, 'analytics:platform')
  return (
    <div className="mx-auto max-w-6xl">
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
          <Tabs defaultValue="requester">
            <TabsList>
              <TabsTrigger value="requester">Requester</TabsTrigger>
              <TabsTrigger value="contributor">Contributor</TabsTrigger>
              {staff && <TabsTrigger value="platform">Platform</TabsTrigger>}
            </TabsList>
            <TabsContent value="requester" className="mt-6 space-y-6">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile
                  label="Total escrowed"
                  icon={Wallet}
                  value={<XlmFigure amount={r.total_escrowed} />}
                />
                <StatTile
                  label="Total paid"
                  icon={CircleDollarSign}
                  value={<XlmFigure amount={r.total_paid} />}
                />
                <StatTile
                  label="Applications received"
                  icon={GitPullRequest}
                  value={formatNumber(r.applications_received)}
                />
                <StatTile
                  label="Time to first application"
                  icon={Clock3}
                  value={
                    r.avg_time_to_first_application_hours === null
                      ? '—'
                      : `${r.avg_time_to_first_application_hours.toFixed(1)} h`
                  }
                  hint="Average across your bounties"
                />
              </div>
              <div className="grid gap-6 lg:grid-cols-2">
                <MonthlyChart
                  title="Spending by month"
                  description="Confirmed payouts you released"
                  data={r.spending_by_month}
                />
                <StatusChart title="Bounties by status" counts={r.bounties_by_status} />
              </div>
            </TabsContent>
            <TabsContent value="contributor" className="mt-6 space-y-6">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                <StatTile
                  label="Total earned"
                  icon={CircleDollarSign}
                  value={<XlmFigure amount={c.total_earned} />}
                />
                <StatTile
                  label="Completed bounties"
                  icon={FileCheck2}
                  value={formatNumber(c.completed_count)}
                />
              </div>
              {c.earnings_by_month.length === 0 && c.completed_count === 0 ? (
                <EmptyState
                  icon={ChartNoAxesCombined}
                  title="No earnings yet"
                  description="Your earnings chart fills in after your first approved submission is paid out."
                />
              ) : (
                <MonthlyChart
                  title="Earnings by month"
                  description="Confirmed payouts received"
                  data={c.earnings_by_month}
                />
              )}
              <div className="grid gap-6 lg:grid-cols-2">
                <StatusChart title="Applications by status" counts={c.applications_by_status} />
                <StatusChart title="Submissions by status" counts={c.submissions_by_status} />
              </div>
            </TabsContent>
            {staff && (
              <TabsContent value="platform" className="mt-6">
                <PlatformAnalyticsPanel />
              </TabsContent>
            )}
          </Tabs>
        )}
      </QueryView>
    </div>
  )
}
