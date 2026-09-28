import { BriefcaseBusiness, CalendarDays, CheckCircle2, Globe, ShieldCheck, Wallet } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyGridSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { GithubMark } from '@/components/brand/GithubMark'
import { MonoValue } from '@/components/common/MonoValue'
import { StatTile } from '@/components/common/StatTile'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { ListSkeleton, LoadingState } from '@/components/layout/LoadingState'
import { PageContainer } from '@/components/layout/PageContainer'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { isApiError } from '@/lib/api/client'
import { usePublicConfig } from '@/lib/api/queries/config'
import { usePublicProfile, useUserBounties, useUserContributions } from '@/lib/api/queries/users'
import type { PublicProfile } from '@/lib/api/types'
import { formatDate, formatNumber, formatPercent } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { accountExplorerUrl, networkDisplayName, txExplorerUrl } from '@/lib/stellar/explorer'

import NotFoundPage from '../NotFoundPage'

const safeUrl = (u: string | null) => (u && /^https:\/\//i.test(u) ? u : null)

function Wallets({ profile }: { profile: PublicProfile }) {
  const { data: config } = usePublicConfig()
  if (profile.wallets.length === 0) {
    return <p className="text-sm text-muted-foreground">No verified wallets linked.</p>
  }
  return (
    <ul className="space-y-3">
      {profile.wallets.map((w) => {
        return (
          <li key={w.public_address} className="rounded-lg border p-3">
            <MonoValue
              value={w.public_address}
              label="wallet address"
              href={accountExplorerUrl(config, w.public_address)}
            />
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="success">
                <ShieldCheck aria-hidden /> Ownership verified by signature
              </Badge>
              <span className="text-muted-foreground">
                {networkDisplayName(w.network)}, verified {formatDate(w.verified_at)}
              </span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function CreatedBounties({ username }: { username: string }) {
  const [page, setPage] = useState(1)
  const { data, isPending, isError, error, refetch } = useUserBounties(username, { page, page_size: 6 })
  if (isPending) return <BountyGridSkeleton count={2} />
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />
  if (data.items.length === 0) {
    return (
      <EmptyState
        icon={BriefcaseBusiness}
        title="No public bounties"
        description="This user hasn’t published any bounties yet."
      />
    )
  }
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        {data.items.map((b) => (
          <BountyCard key={b.id} bounty={b} />
        ))}
      </div>
      <PaginationBar
        page={data.page}
        pages={data.pages}
        total={data.total}
        pageSize={data.page_size}
        onPageChange={setPage}
        itemLabel="bounties"
      />
    </>
  )
}

function Contributions({ username }: { username: string }) {
  const [page, setPage] = useState(1)
  const { data: config } = usePublicConfig()
  const { data, isPending, isError, error, refetch } = useUserContributions(username, { page, page_size: 10 })
  if (isPending) return <ListSkeleton rows={3} />
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />
  if (data.items.length === 0) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="No completed contributions yet"
        description="Completed and paid bounties will appear here."
      />
    )
  }
  return (
    <>
      <ul className="divide-y rounded-xl border">
        {data.items.map((c) => {
          const href = txExplorerUrl(config, c.transaction_hash)
          return (
            <li
              key={`${c.bounty.id}-${c.completed_at}`}
              className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <Link
                  to={`/bounties/${c.bounty.slug || c.bounty.id}`}
                  className="block truncate font-medium hover:underline"
                >
                  {c.bounty.title}
                </Link>
                <div className="text-xs text-muted-foreground">Completed {formatDate(c.completed_at)}</div>
              </div>
              <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                {c.amount && (
                  <span className="font-medium tabular-nums">
                    {formatAmount(c.amount)} <span className="text-muted-foreground">XLM</span>
                  </span>
                )}
                {c.transaction_hash ? (
                  <MonoValue
                    value={c.transaction_hash}
                    label="payout transaction hash"
                    href={href}
                    lead={4}
                    tail={4}
                  />
                ) : (
                  <Badge variant="muted">Payout pending</Badge>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      <PaginationBar
        page={data.page}
        pages={data.pages}
        total={data.total}
        pageSize={data.page_size}
        onPageChange={setPage}
        itemLabel="contributions"
      />
    </>
  )
}

export default function PublicProfilePage() {
  const { username } = useParams()
  const { data: profile, isPending, isError, error, refetch } = usePublicProfile(username)

  if (isError) {
    if (isApiError(error) && error.status === 404) return <NotFoundPage />
    return (
      <PageContainer className="py-16">
        <ErrorState error={error} title="Could not load this profile" onRetry={() => refetch()} />
      </PageContainer>
    )
  }

  return (
    <Bones
      name="public-profile"
      loading={isPending}
      fallback={<LoadingState label="Loading profile" className="min-h-[60vh]" />}
    >
      {profile && <ProfileView profile={profile} />}
    </Bones>
  )
}

function ProfileView({ profile }: { profile: PublicProfile }) {
  const s = profile.stats
  const github = safeUrl(profile.github_url)
  const portfolio = safeUrl(profile.portfolio_url)

  return (
    <PageContainer className="py-10 sm:py-14">
      <header className="flex flex-col gap-6 sm:flex-row sm:items-start">
        <UserAvatar user={profile} className="size-20 text-lg" />
        <div className="min-w-0 flex-1">
          <h1 className="text-3xl font-semibold tracking-tight">{profile.display_name}</h1>
          <p className="text-muted-foreground">@{profile.username}</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="size-4" aria-hidden /> Joined {formatDate(profile.joined_at)}
            </span>
            {github && (
              <a
                href={github}
                target="_blank"
                rel="noopener noreferrer nofollow me"
                className="inline-flex min-h-9 items-center gap-1.5 hover:text-foreground"
              >
                <GithubMark /> GitHub
              </a>
            )}
            {portfolio && (
              <a
                href={portfolio}
                target="_blank"
                rel="noopener noreferrer nofollow me"
                className="inline-flex min-h-9 items-center gap-1.5 hover:text-foreground"
              >
                <Globe className="size-4" aria-hidden /> Portfolio
              </a>
            )}
          </div>
        </div>
      </header>

      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-10">
          <section aria-labelledby="stats-h">
            <h2 id="stats-h" className="text-lg font-semibold">
              Marketplace stats
            </h2>
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatTile label="Bounties created" value={formatNumber(s.bounties_created)} />
              <StatTile
                label="Completed as requester"
                value={formatNumber(s.bounties_completed_as_requester)}
              />
              <StatTile
                label="Contributions completed"
                value={formatNumber(s.contributions_completed)}
              />
              <StatTile label="Applications" value={formatNumber(s.applications_submitted)} />
              <StatTile
                label="Acceptance rate"
                value={formatPercent(s.acceptance_rate)}
                hint="Accepted / decided applications"
              />
              <StatTile
                label="Approval rate"
                value={formatPercent(s.approval_rate)}
                hint="Approved / reviewed submissions"
              />
              <StatTile
                label="Rewards received"
                value={
                  <>
                    {formatAmount(s.total_rewards_received, { maxDecimals: 2 })}{' '}
                    <span className="text-sm font-normal text-muted-foreground">XLM</span>
                  </>
                }
                hint="Confirmed on-chain payouts only"
              />
              <StatTile
                label="Rewards paid"
                value={
                  <>
                    {formatAmount(s.total_rewards_paid, { maxDecimals: 2 })}{' '}
                    <span className="text-sm font-normal text-muted-foreground">XLM</span>
                  </>
                }
              />
            </div>
          </section>

          <Tabs defaultValue="bounties">
            <TabsList>
              <TabsTrigger value="bounties">Created bounties</TabsTrigger>
              <TabsTrigger value="contributions">Contribution history</TabsTrigger>
            </TabsList>
            <TabsContent value="bounties" className="mt-4">
              <CreatedBounties username={profile.username} />
            </TabsContent>
            <TabsContent value="contributions" className="mt-4">
              <Contributions username={profile.username} />
            </TabsContent>
          </Tabs>
        </div>

        <aside className="space-y-6" aria-label="Profile details">
          <section aria-labelledby="about-h" className="rounded-xl border bg-card p-5 shadow-soft">
            <h2 id="about-h" className="text-sm font-medium">
              About
            </h2>
            <p className="mt-2 text-sm whitespace-pre-line text-muted-foreground">
              {profile.bio || 'No bio yet.'}
            </p>
            {profile.skills.length > 0 && (
              <>
                <h3 className="mt-4 text-xs font-medium text-muted-foreground">Skills</h3>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {profile.skills.map((sk) => (
                    <li
                      key={sk}
                      className="rounded-md border bg-surface-raised px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      {sk}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {profile.interests.length > 0 && (
              <>
                <h3 className="mt-4 text-xs font-medium text-muted-foreground">Interests</h3>
                <p className="mt-1 text-sm text-muted-foreground">{profile.interests.join(', ')}</p>
              </>
            )}
            <p className="mt-4 text-xs text-muted-foreground">
              Bio, skills, and links are self-reported and not verified.
            </p>
          </section>

          <section aria-labelledby="wallets-h" className="rounded-xl border bg-card p-5 shadow-soft">
            <h2 id="wallets-h" className="flex items-center gap-2 text-sm font-medium">
              <Wallet className="size-4 text-muted-foreground" aria-hidden /> Wallets
            </h2>
            <div className="mt-3">
              <Wallets profile={profile} />
            </div>
          </section>
        </aside>
      </div>
    </PageContainer>
  )
}
