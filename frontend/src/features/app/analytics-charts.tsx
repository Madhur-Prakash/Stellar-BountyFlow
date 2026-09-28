/**
 * The recharts parts of the analytics pages. This module is only loaded (React.lazy) once a chart renders, so
 * recharts stays out of the analytics page chunk. Every figure these charts show is also in a table for
 * screen readers, rendered by the page itself.
 */
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, XAxis, YAxis } from 'recharts'

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'

export type MonthlyPoint = { label: string; amount: number }
export type StatusPoint = { status: string; count: number }
export type SeriesSpec = { key: string; label: string; color: string }

const moneyConfig = { amount: { label: 'XLM', color: 'var(--chart-1)' } }
const countConfig = { count: { label: 'Count', color: 'var(--chart-1)' } }

export function MonthlyAmountChart({ rows, height }: { rows: MonthlyPoint[]; height: number }) {
  return (
    <ChartContainer config={moneyConfig} className="aspect-auto w-full" style={{ height }}>
      <BarChart data={rows} accessibilityLayer margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} minTickGap={12} />
        <YAxis tickLine={false} axisLine={false} width={48} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
        <Bar
          dataKey="amount"
          fill="var(--color-amount)"
          radius={[4, 4, 0, 0]}
          maxBarSize={36}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartContainer>
  )
}

export function StatusCountChart({ rows, height }: { rows: StatusPoint[]; height: number }) {
  return (
    <ChartContainer config={countConfig} className="aspect-auto w-full" style={{ height }}>
      <BarChart
        data={rows}
        layout="vertical"
        accessibilityLayer
        margin={{ top: 0, right: 36, left: 0, bottom: 0 }}
      >
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis type="category" dataKey="status" tickLine={false} axisLine={false} width={120} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
        <Bar dataKey="count" fill="var(--color-count)" radius={4} maxBarSize={20} isAnimationActive={false}>
          <LabelList
            dataKey="count"
            position="right"
            offset={8}
            className="fill-foreground font-medium tabular-nums"
            fontSize={12}
          />
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

export function ActivityLineChart<T extends { label: string }>({
  rows,
  series,
  height,
}: {
  rows: T[]
  series: SeriesSpec[]
  height: number
}) {
  const config = Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }]))
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height }}>
      <LineChart data={rows} accessibilityLayer margin={{ top: 4, left: 4, right: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} />
        <YAxis tickLine={false} axisLine={false} width={32} allowDecimals={false} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent className="flex-wrap gap-x-4 gap-y-1" />} />
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            stroke={`var(--color-${s.key})`}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ChartContainer>
  )
}
