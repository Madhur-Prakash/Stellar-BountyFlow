import {
  Activity,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  FileCheck2,
  GitPullRequest,
  Hammer,
  ListChecks,
  PlusCircle,
  RotateCcw,
  Search,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router'

import { DeadlineCountdown } from '@/components/bounty/DeadlineCountdown'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { EmailNotVerifiedNotice } from '@/components/common/EmailNotVerifiedNotice'
import { StatGrid, StatTile } from '@/components/common/StatTile'
import { UserAvatar } from '@/components/common/UserAvatar'
import { EmptyState } from '@/components/layout/EmptyState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { reasonText } from '@/features/public/marketplace/recommendation-reason'
import { useDashboard } from '@/lib/api/queries/analytics'
import { useMe } from '@/lib/api/queries/auth'
import type { BountySummary, Dashboard, Me } from '@/lib/api/types'
import {
  CATEGORY_LABELS,
  describeActivity,
  DIFFICULTY_LABELS,
  formatDateTime,
  formatNumber,
  formatRelative,
} from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

import { Money } from './workspace-ui'

const ONBOARDING_STEPS = [
  'email_verified',
  'role_selected',
  'profile_completed',
  'wallet_connected',
  'first_action_taken',
] as const

const plural = (n: number, one: string, many: string) => `${formatNumber(n)} ${n === 1 ? one : many}`
const bountyHref = (b: Pick<BountySummary, 'slug' | 'id'>) => `/bounties/${b.slug || b.id}`

/** A figure in a stat strip that opens the page behind it. */
function StatLink({
  to,
  label,
  value,
  className,
}: {
  to: string
  label: string
  value: number
  className?: string
}) {
  return (
    <Link
      to={to}
      className={cn(
        'min-w-0 bg-card transition-colors hover:bg-surface focus-visible:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset',
        className,
      )}
    >
      <StatTile label={label} value={formatNumber(value)} className="bg-transparent px-4 sm:px-5" />
    </Link>
  )
}

function SectionLabel({ id, children }: { id: string; children: string }) {
  return (
    <h2 id={id} className="label-mono mb-2.5">
      {children}
    </h2>
  )
}

type AttentionItem = { key: string; icon: LucideIcon; title: string; detail?: string; to: string }

function attentionItems(d: Dashboard, me: Me | undefined | null): AttentionItem[] {
  const items: AttentionItem[] = []
  if (me && !me.onboarding.completed) {
    const done = ONBOARDING_STEPS.filter((k) => me.onboarding[k]).length
    items.push({
      key: 'onboarding',
      icon: ListChecks,
      title: 'Finish setting up your account',
      detail: `${done} of ${ONBOARDING_STEPS.length} steps done`,
      to: '/app/onboarding',
    })
  }
  if (d.pending_applications_to_review > 0)
    items.push({
      key: 'applications',
      icon: GitPullRequest,
      title: `${plural(d.pending_applications_to_review, 'application', 'applications')} to review`,
      detail: 'On bounties you posted',
      to: '/app/bounties',
    })
  if (d.submissions_awaiting_review > 0)
    items.push({
      key: 'submissions',
      icon: FileCheck2,
      title: `${plural(d.submissions_awaiting_review, 'submission', 'submissions')} to review`,
      detail: 'On bounties you posted',
      to: '/app/bounties',
    })
  if (d.pending_payments > 0)
    items.push({
      key: 'payouts',
      icon: CircleDollarSign,
      title: `${plural(d.pending_payments, 'payout', 'payouts')} pending`,
      detail: 'Approved work not yet paid out',
      to: '/app/payments',
    })
  if (d.revision_requests > 0)
    items.push({
      key: 'revisions',
      icon: RotateCcw,
      title: `${plural(d.revision_requests, 'revision request', 'revision requests')}`,
      detail: 'Send a revised version',
      to: '/app/submissions',
    })
  if (d.my_active_assignments > 0)
    items.push({
      key: 'assignments',
      icon: Hammer,
      title: `${plural(d.my_active_assignments, 'active assignment', 'active assignments')}`,
      detail: 'Work you’ve been accepted for',
      to: '/app/submissions',
    })
  return items
}

function AttentionCard({ d, me }: { d: Dashboard; me: Me | undefined | null }) {
  const items = attentionItems(d, me)
  return (
    <section aria-labelledby="attention-h">
      <Card className="gap-0 pb-0">
        <CardHeader className="pb-4">
          <CardTitle>
            <h2 id="attention-h">Needs your attention</h2>
          </CardTitle>
        </CardHeader>
        {items.length === 0 ? (
          <div className="flex items-center gap-2.5 border-t px-5 py-5 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4 shrink-0" aria-hidden /> You’re all caught up.
          </div>
        ) : (
          <ul className="divide-y border-t">
            {items.map((item) => (
              <li key={item.key}>
                <Link
                  to={item.to}
                  className="group flex items-center gap-3 px-5 py-3 transition-colors hover:bg-surface/70 focus-visible:bg-surface/70 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset"
                >
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-surface text-muted-foreground">
                    <item.icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{item.title}</span>
                    {item.detail && (
                      <span className="block truncate text-xs text-muted-foreground">{item.detail}</span>
                    )}
                  </span>
                  <ChevronRight
                    className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
                    aria-hidden
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </section>
  )
}

/**
 * One bounty in a dashboard list. The wide variant gives the funding badge its own column from sm up; the
 * narrow one (a side column) keeps it under the title.
 */
function BountyRow({
  bounty,
  variant,
  reason,
}: {
  bounty: BountySummary
  variant: 'open' | 'completed'
  /** Why it was recommended, e.g. "Matches rust, soroban". */
  reason?: string | null
}) {
  const wide = variant === 'open'
  const badge = <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
  return (
    <li className="px-4 py-3 sm:px-5">
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <Link to={bountyHref(bounty)} className="line-clamp-2 text-sm font-medium hover:underline">
            {bounty.title}
          </Link>
          {reason && <p className="mt-0.5 text-xs text-foreground/80">{reason}</p>}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{CATEGORY_LABELS[bounty.category]}</span>
            {wide ? (
              <>
                <span>{DIFFICULTY_LABELS[bounty.difficulty]}</span>
                <DeadlineCountdown deadline={bounty.application_deadline} className="text-xs" />
              </>
            ) : (
              <span>by {bounty.requester.display_name}</span>
            )}
          </div>
        </div>
        {wide && <div className="hidden shrink-0 pt-0.5 sm:block">{badge}</div>}
        <div className="shrink-0 pt-0.5 text-right text-sm sm:min-w-24">
          <Money amount={formatAmount(bounty.reward_amount)} asset={bounty.reward_asset.code} />
        </div>
      </div>
      <div className={cn('mt-2', wide && 'sm:hidden')}>{badge}</div>
    </li>
  )
}

function RecommendedCard({
  items,
  reasons,
  hasSkills,
}: {
  items: BountySummary[]
  reasons?: Dashboard['recommendation_reasons']
  hasSkills: boolean
}) {
  return (
    <section aria-labelledby="rec-h">
      <Card className="gap-0 pb-0">
        <CardHeader className="pb-4">
          <CardTitle>
            <h2 id="rec-h">Recommended for you</h2>
          </CardTitle>
          <CardAction>
            <Button asChild variant="outline" size="sm">
              <Link to="/bounties">View marketplace</Link>
            </Button>
          </CardAction>
        </CardHeader>
        {items.length === 0 ? (
          <EmptyState
            icon={BriefcaseBusiness}
            title="No recommendations yet"
            description={
              hasSkills
                ? 'Nothing open matches your skills right now. New bounties are matched as they are posted.'
                : 'Add skills to your profile and we’ll suggest matching bounties.'
            }
            action={
              <Button asChild variant="outline">
                <Link to="/app/profile">{hasSkills ? 'Edit skills' : 'Add skills'}</Link>
              </Button>
            }
            className="rounded-none border-0 border-t bg-transparent py-10"
          />
        ) : (
          <ul className="divide-y border-t">
            {items.slice(0, 6).map((b) => (
              <BountyRow key={b.id} bounty={b} variant="open" reason={reasonText(reasons?.[b.id])} />
            ))}
          </ul>
        )}
      </Card>
    </section>
  )
}

function ActivityCard({ items }: { items: Dashboard['recent_activity'] }) {
  return (
    <section aria-labelledby="act-h">
      <Card className="gap-0 pb-0">
        <CardHeader className="pb-4">
          <CardTitle>
            <h2 id="act-h">Recent activity</h2>
          </CardTitle>
        </CardHeader>
        {items.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No activity yet"
            description="Activity on your bounties and applications will show up here."
            className="rounded-none border-0 border-t bg-transparent py-10"
          />
        ) : (
          <ul className="divide-y border-t">
            {items.slice(0, 10).map((a) => (
              <li key={a.id} className="flex gap-3 px-5 py-3 text-sm">
                {a.actor ? (
                  <UserAvatar user={a.actor} className="size-7" />
                ) : (
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full border bg-surface">
                    <Activity className="size-3.5 text-muted-foreground" aria-hidden />
                  </span>
                )}
                <div className="min-w-0">
                  <p className="leading-snug">
                    <span className="font-medium">{a.actor?.display_name ?? 'BountyFlow'}</span>{' '}
                    <span className="text-muted-foreground">{describeActivity(a.action, !!a.bounty)}</span>
                    {a.bounty && (
                      <>
                        {' '}
                        <Link to={bountyHref(a.bounty)} className="font-medium hover:underline">
                          {a.bounty.title}
                        </Link>
                      </>
                    )}
                  </p>
                  <time
                    dateTime={a.created_at}
                    title={formatDateTime(a.created_at)}
                    className="mt-0.5 block text-xs text-muted-foreground"
                  >
                    {formatRelative(a.created_at)}
                  </time>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </section>
  )
}

function CompletedCard({ items }: { items: BountySummary[] }) {
  return (
    <section aria-labelledby="done-h">
      <Card className="gap-0 pb-0">
        <CardHeader className="pb-4">
          <CardTitle>
            <h2 id="done-h">Recently completed</h2>
          </CardTitle>
        </CardHeader>
        <ul className="divide-y border-t">
          {items.slice(0, 5).map((b) => (
            <BountyRow key={b.id} bounty={b} variant="completed" />
          ))}
        </ul>
      </Card>
    </section>
  )
}

function DashboardContent({ d, me }: { d: Dashboard; me: Me | undefined | null }) {
  return (
    <div className="space-y-6">
      <section aria-labelledby="req-h">
        <SectionLabel id="req-h">As a requester</SectionLabel>
        <StatGrid className="grid-cols-2 xl:grid-cols-4">
          <StatLink to="/app/bounties" label="Active bounties" value={d.active_bounties} />
          <StatLink
            to="/app/bounties"
            label="Applications to review"
            value={d.pending_applications_to_review}
          />
          <StatLink to="/app/bounties" label="Submissions to review" value={d.submissions_awaiting_review} />
          <StatLink to="/app/payments" label="Payouts pending" value={d.pending_payments} />
        </StatGrid>
      </section>

      <section aria-labelledby="con-h">
        <SectionLabel id="con-h">As a contributor</SectionLabel>
        <StatGrid className="grid-cols-2 sm:grid-cols-3">
          <StatLink to="/app/applications" label="Pending applications" value={d.my_pending_applications} />
          <StatLink to="/app/submissions" label="Active assignments" value={d.my_active_assignments} />
          <StatLink
            to="/app/submissions"
            label="Revision requests"
            value={d.revision_requests}
            className="max-sm:col-span-full"
          />
        </StatGrid>
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22.5rem)]">
        <div className="min-w-0 space-y-6">
          <AttentionCard d={d} me={me} />
          <RecommendedCard
            items={d.recommendations}
            reasons={d.recommendation_reasons}
            hasSkills={!!me?.skills.length}
          />
        </div>
        <div className="min-w-0 space-y-6">
          <ActivityCard items={d.recent_activity} />
          {d.recent_completed.length > 0 && <CompletedCard items={d.recent_completed} />}
        </div>
      </div>
    </div>
  )
}

function DashboardFallback() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading">
      <Skeleton className="h-22 rounded-xl" />
      <Skeleton className="h-22 rounded-xl" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22.5rem)]">
        <div className="space-y-6">
          <Skeleton className="h-44 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
        <Skeleton className="h-136 rounded-xl" />
      </div>
      <span className="sr-only">Loading…</span>
    </div>
  )
}

export default function DashboardPage() {
  const { data: me } = useMe()
  const query = useDashboard()

  return (
    <div>
      <PageHeader
        title={me ? `Welcome back, ${me.display_name.split(' ')[0]}` : 'Dashboard'}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/bounties">
                <Search /> Find work
              </Link>
            </Button>
            <Button asChild>
              <Link to="/app/bounties/create">
                <PlusCircle /> Post a bounty
              </Link>
            </Button>
          </>
        }
      />

      {me && !me.email_verified && <EmailNotVerifiedNotice className="mb-6" />}

      <QueryView
        query={query}
        skeleton="dashboard"
        loading={<DashboardFallback />}
        errorTitle="Could not load your dashboard"
      >
        {(d) => <DashboardContent d={d} me={me} />}
      </QueryView>
    </div>
  )
}
