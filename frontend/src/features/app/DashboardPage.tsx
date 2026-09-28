import {
  Activity,
  BriefcaseBusiness,
  CircleDollarSign,
  Clock3,
  FileCheck2,
  GitPullRequest,
  Hammer,
  PlusCircle,
  RotateCcw,
} from 'lucide-react'
import { Link } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { EmailNotVerifiedNotice } from '@/components/common/EmailNotVerifiedNotice'
import { StatTile } from '@/components/common/StatTile'
import { UserAvatar } from '@/components/common/UserAvatar'
import { EmptyState } from '@/components/layout/EmptyState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { CountUp } from '@/components/motion/CountUp'
import { Reveal } from '@/components/motion/Reveal'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useDashboard } from '@/lib/api/queries/analytics'
import { useMe } from '@/lib/api/queries/auth'
import { describeActivity, formatRelative } from '@/lib/format'

export default function DashboardPage() {
  const { data: me } = useMe()
  const query = useDashboard()

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title={me ? `Welcome back, ${me.display_name.split(' ')[0]}` : 'Dashboard'}
        description="What needs your attention across the bounties you run and the work you do."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/bounties">Find work</Link>
            </Button>
            <Button asChild>
              <Link to="/app/bounties/create">
                <PlusCircle /> Post a bounty
              </Link>
            </Button>
          </>
        }
      />

      <div className="space-y-4">
        {me && !me.onboarding.completed && (
          <Alert variant="info">
            <Clock3 />
            <AlertTitle>Finish setting up your account</AlertTitle>
            <AlertDescription>
              <p>
                A few steps left, including connecting a wallet so you can fund bounties or receive payouts.
              </p>
              <Button asChild size="sm" variant="outline" className="mt-2">
                <Link to="/app/onboarding">Continue onboarding</Link>
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {me && !me.email_verified && <EmailNotVerifiedNotice />}
      </div>

      <QueryView
        query={query}
        skeleton="dashboard"
        loading={
          <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        }
        errorTitle="Could not load your dashboard"
      >
        {(d) => (
          <div className="mt-6 space-y-10">
            <section aria-labelledby="req-h">
              <h2 id="req-h" className="mb-3 text-sm font-medium text-muted-foreground">
                As a requester
              </h2>
              <Reveal className="grid grid-cols-2 gap-3 lg:grid-cols-4" y={14} stagger={0.05}>
                {[
                  {
                    label: 'Active bounties',
                    value: d.active_bounties,
                    icon: BriefcaseBusiness,
                    to: '/app/bounties',
                  },
                  {
                    label: 'Applications to review',
                    value: d.pending_applications_to_review,
                    icon: GitPullRequest,
                    to: '/app/bounties',
                  },
                  {
                    label: 'Submissions to review',
                    value: d.submissions_awaiting_review,
                    icon: FileCheck2,
                    to: '/app/bounties',
                  },
                  {
                    label: 'Payouts pending',
                    value: d.pending_payments,
                    icon: CircleDollarSign,
                    to: '/app/payments',
                  },
                ].map((t) => (
                  <div key={t.label}>
                    <Link to={t.to} className="block rounded-xl focus-visible:outline-2">
                      <StatTile
                        label={t.label}
                        value={<CountUp value={t.value} />}
                        icon={t.icon}
                        className="transition-colors hover:border-foreground/20"
                      />
                    </Link>
                  </div>
                ))}
              </Reveal>
            </section>

            <section aria-labelledby="con-h">
              <h2 id="con-h" className="mb-3 text-sm font-medium text-muted-foreground">
                As a contributor
              </h2>
              <Reveal className="grid grid-cols-2 gap-3 lg:grid-cols-3" y={14} stagger={0.05}>
                {[
                  {
                    label: 'Pending applications',
                    value: d.my_pending_applications,
                    icon: Clock3,
                    to: '/app/applications',
                  },
                  {
                    label: 'Active assignments',
                    value: d.my_active_assignments,
                    icon: Hammer,
                    to: '/app/submissions',
                  },
                  {
                    label: 'Revision requests',
                    value: d.revision_requests,
                    icon: RotateCcw,
                    to: '/app/submissions',
                  },
                ].map((t) => (
                  <div key={t.label}>
                    <Link to={t.to} className="block rounded-xl">
                      <StatTile
                        label={t.label}
                        value={<CountUp value={t.value} />}
                        icon={t.icon}
                        className="transition-colors hover:border-foreground/20"
                      />
                    </Link>
                  </div>
                ))}
              </Reveal>
            </section>

            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
              <section aria-labelledby="rec-h">
                <div className="mb-3 flex items-center justify-between">
                  <h2 id="rec-h" className="font-semibold">
                    Recommended for you
                  </h2>
                  <Button asChild variant="ghost" size="sm">
                    <Link to="/bounties">Marketplace</Link>
                  </Button>
                </div>
                {d.recommendations.length === 0 ? (
                  <EmptyState
                    icon={BriefcaseBusiness}
                    title="No recommendations yet"
                    description="Add skills to your profile and we’ll suggest matching bounties."
                    action={
                      <Button asChild variant="outline">
                        <Link to="/app/profile">Add skills</Link>
                      </Button>
                    }
                  />
                ) : (
                  <Reveal className="grid gap-4 md:grid-cols-2">
                    {d.recommendations.slice(0, 4).map((b) => (
                      <BountyCard key={b.id} bounty={b} />
                    ))}
                  </Reveal>
                )}
              </section>

              <section aria-labelledby="act-h">
                <h2 id="act-h" className="mb-3 font-semibold">
                  Recent activity
                </h2>
                {d.recent_activity.length === 0 ? (
                  <EmptyState
                    icon={Activity}
                    title="Quiet so far"
                    description="Activity on your bounties and applications will show up here."
                  />
                ) : (
                  <ul className="divide-y rounded-xl border bg-card shadow-soft">
                    {d.recent_activity.slice(0, 10).map((a) => (
                      <li key={a.id} className="flex gap-3 p-3 text-sm">
                        {a.actor ? (
                          <UserAvatar user={a.actor} className="size-7" />
                        ) : (
                          <Activity className="mt-1 size-4 text-muted-foreground" aria-hidden />
                        )}
                        <div className="min-w-0">
                          <p>
                            <span className="font-medium">{a.actor?.display_name ?? 'BountyFlow'}</span>{' '}
                            <span className="text-muted-foreground">
                              {describeActivity(a.action, !!a.bounty)}
                            </span>
                            {a.bounty && (
                              <>
                                {' '}
                                <Link
                                  to={`/bounties/${a.bounty.slug || a.bounty.id}`}
                                  className="font-medium hover:underline"
                                >
                                  {a.bounty.title}
                                </Link>
                              </>
                            )}
                          </p>
                          <time dateTime={a.created_at} className="text-xs text-muted-foreground">
                            {formatRelative(a.created_at)}
                          </time>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>

            {d.recent_completed.length > 0 && (
              <section aria-labelledby="done-h">
                <h2 id="done-h" className="mb-3 font-semibold">
                  Recently completed
                </h2>
                <Reveal className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {d.recent_completed.slice(0, 3).map((b) => (
                    <BountyCard key={b.id} bounty={b} showBookmark={false} />
                  ))}
                </Reveal>
              </section>
            )}
          </div>
        )}
      </QueryView>
    </div>
  )
}
