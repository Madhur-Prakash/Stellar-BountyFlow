import {
  ArrowLeftRight,
  BriefcaseBusiness,
  ChevronRight,
  Flag,
  RefreshCw,
  Scale,
  ScrollText,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router'

import { StatGrid, StatTile } from '@/components/common/StatTile'
import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAdminOverview } from '@/lib/api/queries/admin'
import { useMe } from '@/lib/api/queries/auth'
import type { AdminOverview, Me, Permission } from '@/lib/api/types'
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format'
import { hasPermission } from '@/lib/permissions'
import { networkDisplayName } from '@/lib/stellar/explorer'
import { cn } from '@/lib/utils'

import { HealthBadge } from './admin-shared'

type Area = {
  to: string
  label: string
  description: string
  icon: LucideIcon
  permission: Permission
}

function adminAreas(me: Me | null | undefined): Area[] {
  const areas: Area[] = [
    {
      to: '/admin/users',
      label: 'Users',
      description: hasPermission(me, 'user:manage') ? 'Change roles, suspend accounts' : 'Look up accounts',
      icon: Users,
      permission: 'user:view_all',
    },
    {
      to: '/admin/bounties',
      label: 'Bounties',
      description: 'Hide, cancel or feature bounties',
      icon: BriefcaseBusiness,
      permission: 'bounty:view_all',
    },
    {
      to: '/admin/reports',
      label: 'Reports',
      description: 'Review and close community reports',
      icon: Flag,
      permission: 'report:review',
    },
    {
      to: '/admin/disputes',
      label: 'Disputes',
      description: 'Assign and resolve disputes',
      icon: Scale,
      permission: 'dispute:view_all',
    },
    {
      to: '/admin/transactions',
      label: 'Transactions',
      description: 'Escrow, payout and refund transactions',
      icon: ArrowLeftRight,
      permission: 'transaction:view_all',
    },
    {
      to: '/admin/audit-logs',
      label: 'Audit logs',
      description: 'Who did what, and when',
      icon: ScrollText,
      permission: 'audit:read',
    },
  ]
  return areas.filter((a) => hasPermission(me, a.permission))
}

type CountKey = keyof AdminOverview['counts']
type CountItem = { key: CountKey; label: string; to?: string; attention?: boolean }

const COUNT_GROUPS: { id: string; title: string; grid: string; items: CountItem[] }[] = [
  {
    id: 'people',
    title: 'People',
    grid: 'grid-cols-2 sm:grid-cols-3 [&>*:last-child]:col-span-2 sm:[&>*:last-child]:col-span-1',
    items: [
      { key: 'users_total', label: 'Registered', to: '/admin/users' },
      { key: 'users_active_30d', label: 'Active (30 days)' },
      { key: 'users_suspended', label: 'Suspended', to: '/admin/users' },
    ],
  },
  {
    id: 'bounties',
    title: 'Bounties',
    grid: 'grid-cols-2 sm:grid-cols-3 [&>*:last-child]:col-span-2 sm:[&>*:last-child]:col-span-1',
    items: [
      { key: 'bounties_total', label: 'Total', to: '/admin/bounties' },
      { key: 'bounties_open', label: 'Open' },
      { key: 'bounties_hidden', label: 'Hidden', to: '/admin/bounties' },
    ],
  },
  {
    id: 'attention',
    title: 'Needs attention',
    grid: 'grid-cols-2 xl:grid-cols-5 [&>*:last-child]:col-span-2 xl:[&>*:last-child]:col-span-1',
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
      { key: 'unpublished_outbox_events', label: 'Undelivered events', attention: true },
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
  const flagged = !!item.attention && value > 0
  const tile = (
    <StatTile
      label={item.label}
      value={
        <span className="flex items-center gap-2">
          <span className={cn(flagged && 'text-warning')}>{formatNumber(value)}</span>
          {flagged && <Badge variant="warning">Review</Badge>}
        </span>
      }
      className="h-full bg-transparent [&>div:first-child]:whitespace-normal"
    />
  )
  if (!item.to) return <div className="bg-card">{tile}</div>
  return (
    <Link
      to={item.to}
      className="group relative block bg-card transition-colors outline-none hover:bg-muted/40 focus-visible:z-10 focus-visible:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {tile}
      <ChevronRight
        className="absolute top-4 right-4 size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
        aria-hidden
      />
    </Link>
  )
}

function ServicesCard({ data }: { data: AdminOverview }) {
  return (
    <Card className="gap-0 py-0 [--card-spacing:--spacing(4)]">
      <CardHeader className="border-b pt-4">
        <CardTitle>
          <h2 id="overview-services">Services</h2>
        </CardTitle>
        <CardDescription className="text-[0.8125rem]">
          As of{' '}
          <time dateTime={data.generated_at} className="tabular-nums">
            {formatDateTime(data.generated_at)}
          </time>
        </CardDescription>
        <CardAction className="text-right">
          <div className="text-xs text-muted-foreground">Worker heartbeat</div>
          <div className="text-[0.8125rem] font-medium tabular-nums">
            {data.worker_heartbeat_at ? (
              <time dateTime={data.worker_heartbeat_at} title={formatDateTime(data.worker_heartbeat_at)}>
                {formatRelative(data.worker_heartbeat_at)}
              </time>
            ) : (
              <span className="text-warning">None yet</span>
            )}
          </div>
        </CardAction>
      </CardHeader>
      <ul className="divide-y" aria-labelledby="overview-services">
        {(Object.keys(SERVICE_LABELS) as (keyof AdminOverview['health'])[]).map((k) => (
          <li key={k} className="flex h-11 items-center justify-between gap-3 px-4">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="text-sm font-medium">{SERVICE_LABELS[k]}</span>
              {k === 'blockchain_rpc' && (
                <span className="text-xs text-muted-foreground">{networkDisplayName(data.network)}</span>
              )}
            </span>
            <HealthBadge state={data.health[k] ?? 'error'} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

function AdminAreas({ me }: { me: Me | null | undefined }) {
  const areas = adminAreas(me)
  if (areas.length === 0) return null
  return (
    <Card className="gap-0 py-0 [--card-spacing:--spacing(4)]">
      <CardHeader className="border-b pt-4">
        <CardTitle>
          <h2 id="overview-links">Admin areas</h2>
        </CardTitle>
      </CardHeader>
      <ul className="divide-y" aria-labelledby="overview-links">
        {areas.map(({ to, label, description, icon: Icon }) => (
          <li key={to}>
            <Link
              to={to}
              className="group flex items-center gap-3 px-4 py-2.5 transition-colors outline-none hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset"
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-surface text-muted-foreground">
                <Icon className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm leading-5 font-medium">{label}</span>
                <span className="block truncate text-xs leading-4 text-muted-foreground">{description}</span>
              </span>
              <ChevronRight
                className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
                aria-hidden
              />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function CountGroup({ group, data }: { group: (typeof COUNT_GROUPS)[number]; data: AdminOverview }) {
  return (
    <section aria-labelledby={`overview-${group.id}`} className="min-w-0">
      <h2 id={`overview-${group.id}`} className="label-mono mb-2.5">
        {group.title}
      </h2>
      <StatGrid className={group.grid}>
        {group.items.map((item) => (
          <CountTile key={item.key} item={item} value={data.counts[item.key] ?? 0} />
        ))}
      </StatGrid>
    </section>
  )
}

function OverviewContent({ data, me }: { data: AdminOverview; me: Me | null | undefined }) {
  const [people, bounties, attention] = COUNT_GROUPS as [
    (typeof COUNT_GROUPS)[number],
    (typeof COUNT_GROUPS)[number],
    (typeof COUNT_GROUPS)[number],
  ]
  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <CountGroup group={people} data={data} />
        <CountGroup group={bounties} data={data} />
      </div>
      <CountGroup group={attention} data={data} />
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <ServicesCard data={data} />
        <AdminAreas me={me} />
      </div>
    </div>
  )
}

/** Stand-in shapes until the page's captured bones exist. */
function OverviewFallback() {
  return (
    <div role="status" aria-label="Loading" className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i}>
            <Skeleton className="mb-2.5 h-4 w-28" />
            <Skeleton className="h-21 w-full rounded-xl" />
          </div>
        ))}
      </div>
      <div>
        <Skeleton className="mb-2.5 h-4 w-28" />
        <Skeleton className="h-21 w-full rounded-xl" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-72 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
      <span className="sr-only">Loading…</span>
    </div>
  )
}

export default function AdminOverviewPage() {
  const overview = useAdminOverview()
  const { data: me } = useMe()

  return (
    <div>
      <PageHeader
        title="Admin overview"
        actions={
          <Button variant="outline" onClick={() => overview.refetch()} disabled={overview.isFetching}>
            <RefreshCw className={cn(overview.isFetching && 'animate-spin')} aria-hidden /> Refresh
          </Button>
        }
      />

      <div aria-busy={overview.isFetching}>
        {overview.isError ? (
          <div className="space-y-6">
            <ErrorState
              error={overview.error}
              title="Could not load the overview"
              onRetry={() => overview.refetch()}
            />
            <AdminAreas me={me} />
          </div>
        ) : (
          <Bones name="admin-overview" loading={overview.isPending} fallback={<OverviewFallback />}>
            {overview.data ? <OverviewContent data={overview.data} me={me} /> : null}
          </Bones>
        )}
      </div>
    </div>
  )
}
