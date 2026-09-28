import {
  ArrowLeftRight,
  BriefcaseBusiness,
  Flag,
  HeartPulse,
  RefreshCw,
  Scale,
  ScrollText,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router'

import { StatTile } from '@/components/common/StatTile'
import { ListSkeleton } from '@/components/layout/LoadingState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAdminOverview } from '@/lib/api/queries/admin'
import type { AdminOverview } from '@/lib/api/types'
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format'
import { networkDisplayName } from '@/lib/stellar/explorer'
import { cn } from '@/lib/utils'

import { HealthBadge } from './admin-shared'

const QUICK_LINKS: { to: string; label: string; description: string; icon: LucideIcon }[] = [
  {
    to: '/admin/users',
    label: 'Users',
    description: 'Search accounts, change roles, suspend or reactivate.',
    icon: Users,
  },
  {
    to: '/admin/bounties',
    label: 'Bounties',
    description: 'Hide, unhide, cancel, or feature any bounty.',
    icon: BriefcaseBusiness,
  },
  {
    to: '/admin/reports',
    label: 'Reports',
    description: 'Review community reports and record outcomes.',
    icon: Flag,
  },
  {
    to: '/admin/disputes',
    label: 'Disputes',
    description: 'Assign and resolve disputes between parties.',
    icon: Scale,
  },
  {
    to: '/admin/transactions',
    label: 'Transactions',
    description: 'Monitor escrow, payout, and refund transactions.',
    icon: ArrowLeftRight,
  },
  {
    to: '/admin/audit-logs',
    label: 'Audit logs',
    description: 'Trace who did what, and when.',
    icon: ScrollText,
  },
]

type CountKey = keyof AdminOverview['counts']
type CountItem = { key: CountKey; label: string; to?: string; attention?: boolean; hint?: string }

const COUNT_GROUPS: { id: string; title: string; items: CountItem[] }[] = [
  {
    id: 'people',
    title: 'People',
    items: [
      { key: 'users_total', label: 'Registered users', to: '/admin/users' },
      { key: 'users_active_30d', label: 'Active in the last 30 days' },
      { key: 'users_suspended', label: 'Suspended accounts', to: '/admin/users' },
    ],
  },
  {
    id: 'bounties',
    title: 'Bounties',
    items: [
      { key: 'bounties_total', label: 'All bounties', to: '/admin/bounties' },
      { key: 'bounties_open', label: 'Open right now' },
      { key: 'bounties_hidden', label: 'Hidden by moderation', to: '/admin/bounties' },
    ],
  },
  {
    id: 'attention',
    title: 'Needs attention',
    items: [
      { key: 'open_reports', label: 'Open reports', to: '/admin/reports', attention: true },
      { key: 'open_disputes', label: 'Open disputes', to: '/admin/disputes', attention: true },
      {
        key: 'pending_transactions',
        label: 'Pending transactions',
        to: '/admin/transactions',
        attention: true,
      },
      {
        key: 'failed_transactions_24h',
        label: 'Failed transactions (24h)',
        to: '/admin/transactions',
        attention: true,
      },
      {
        key: 'unpublished_outbox_events',
        label: 'Undelivered events',
        attention: true,
        hint: 'Outbox events the worker has not dispatched yet',
      },
    ],
  },
]

const SERVICE_LABELS: Record<keyof AdminOverview['health'], string> = {
  database: 'Database',
  redis: 'Redis',
  kafka: 'Kafka',
  blockchain_rpc: 'Blockchain RPC',
  worker: 'Worker',
}

function CountTile({ item, value }: { item: CountItem; value: number }) {
  const flagged = item.attention && value > 0
  const tile = (
    <StatTile
      label={item.label}
      value={formatNumber(value)}
      hint={item.hint}
      className={cn('h-full transition-colors', flagged && 'border-warning/40 bg-warning/5')}
    />
  )
  if (!item.to) return tile
  return (
    <Link
      to={item.to}
      className="block h-full rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none hover:[&>div]:border-foreground/20"
    >
      {tile}
    </Link>
  )
}

function OverviewContent({ data }: { data: AdminOverview }) {
  return (
    <div className="space-y-8">
      {COUNT_GROUPS.map((group) => (
        <section key={group.id} aria-labelledby={`overview-${group.id}`}>
          <h2 id={`overview-${group.id}`} className="mb-3 text-lg font-semibold">
            {group.title}
          </h2>
          <ul className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
            {group.items.map((item) => (
              <li key={item.key}>
                <CountTile item={item} value={data.counts[item.key] ?? 0} />
              </li>
            ))}
          </ul>
        </section>
      ))}

      <section aria-labelledby="overview-services">
        <Card>
          <CardHeader>
            <CardTitle id="overview-services" className="flex items-center gap-2">
              <HeartPulse className="size-4 text-muted-foreground" aria-hidden /> Services
            </CardTitle>
            <CardDescription>
              Snapshot from{' '}
              <time dateTime={data.generated_at} className="tabular-nums">
                {formatDateTime(data.generated_at)}
              </time>{' '}
              on the {networkDisplayName(data.network)} network. Refreshes every 30 seconds.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {(Object.keys(SERVICE_LABELS) as (keyof AdminOverview['health'])[]).map((k) => (
                <li key={k} className="flex items-center justify-between gap-2 rounded-lg border p-3">
                  <span className="text-sm font-medium">{SERVICE_LABELS[k]}</span>
                  <HealthBadge state={data.health[k] ?? 'error'} />
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted-foreground">
              Worker heartbeat:{' '}
              {data.worker_heartbeat_at ? (
                <time dateTime={data.worker_heartbeat_at} title={formatDateTime(data.worker_heartbeat_at)}>
                  {formatRelative(data.worker_heartbeat_at)}
                </time>
              ) : (
                'not seen yet. Check that the worker process is running.'
              )}
            </p>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}

export default function AdminOverviewPage() {
  const overview = useAdminOverview()

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Admin overview"
        description="Platform counts and service health, as reported by the API."
        actions={
          <Button variant="outline" onClick={() => overview.refetch()} disabled={overview.isFetching}>
            <RefreshCw className={cn(overview.isFetching && 'animate-spin')} aria-hidden /> Refresh
          </Button>
        }
      />

      <div className="space-y-10">
        <div aria-busy={overview.isFetching}>
          <QueryView
            query={overview}
            errorTitle="Could not load the overview"
            loading={<ListSkeleton rows={4} />}
            skeleton="admin-overview"
          >
            {(data) => <OverviewContent data={data} />}
          </QueryView>
        </div>

        <section aria-labelledby="overview-links">
          <h2 id="overview-links" className="mb-3 text-lg font-semibold">
            Admin areas
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {QUICK_LINKS.map(({ to, label, description, icon: Icon }) => (
              <li key={to}>
                <Link
                  to={to}
                  className="group flex h-full items-start gap-3 rounded-lg border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                >
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-surface-raised text-muted-foreground">
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{label}</span>
                    <span className="mt-0.5 block text-sm text-muted-foreground">{description}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}
