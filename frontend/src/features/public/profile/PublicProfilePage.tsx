import { BriefcaseBusiness, CalendarDays, CheckCircle2, Globe, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyGridSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { SkillTags } from '@/components/bounty/SkillTags'
import { GithubMark } from '@/components/brand/GithubMark'
import { MonoValue } from '@/components/common/MonoValue'
import { StatGrid, StatTile } from '@/components/common/StatTile'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { ListSkeleton, LoadingState } from '@/components/layout/LoadingState'
import { PageContainer } from '@/components/layout/PageContainer'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
    return <p className="text-sm text-muted-foreground">No verified wallets.</p>
  }
  return (
    <ul className="divide-y">
      {profile.wallets.map((w) => (
        <li key={w.public_address} className="py-3 first:pt-0 last:pb-0">
          <MonoValue
            value={w.public_address}
            label="wallet address"
            href={accountExplorerUrl(config, w.public_address)}
            className="-my-1"
          />
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="success">
              <ShieldCheck aria-hidden /> Verified by signature
            </Badge>
            <span>
              {networkDisplayName(w.network)}, {formatDate(w.verified_at)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  )
}

function CreatedBounties({ username }: { username: string }) {
  const [page, setPage] = useState(1)
  const { data, isPending, isError, error, refetch } = useUserBounties(username, { page, page_size: 6 })
  if (isPending) return <BountyGridSkeleton count={3} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" />
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />
  if (data.items.length === 0) {
    return <EmptyState icon={BriefcaseBusiness} title="No public bounties yet" />
  }
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {data.items.map((b) => (
          <BountyCard key={b.id} bounty={b} showRequester={false} />
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
    return <EmptyState icon={CheckCircle2} title="No completed contributions yet" />
  }
  return (
    <>
      <ul className="divide-y overflow-hidden rounded-xl border bg-card shadow-soft">
        {data.items.map((c) => {
          const href = txExplorerUrl(config, c.transaction_hash)
          return (
            <li
              key={`${c.bounty.id}-${c.completed_at}`}
              className="flex flex-col gap-2 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <Link
                  to={`/bounties/${c.bounty.slug || c.bounty.id}`}
                  className="block truncate text-sm font-medium hover:underline"
                >
                  {c.bounty.title}
                </Link>
                <div className="text-xs text-muted-foreground">Completed {formatDate(c.completed_at)}</div>
              </div>
              <div className="flex flex-wrap items-center gap-3 sm:justify-end">
                {c.amount && (
                  <span className="text-sm">
                    <span className="amount">{formatAmount(c.amount)}</span>{' '}
                    <span className="text-xs text-muted-foreground">XLM</span>
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

function Xlm({ amount }: { amount: string }) {
  return (
    <>
      {formatAmount(amount, { maxDecimals: 2 })}{' '}
      <span className="text-sm font-normal text-muted-foreground">XLM</span>
    </>
  )
}

function ProfileView({ profile }: { profile: PublicProfile }) {
  const s = profile.stats
  const github = safeUrl(profile.github_url)
  const portfolio = safeUrl(profile.portfolio_url)
  const linkClass =
    'inline-flex min-h-9 items-center gap-1.5 text-muted-foreground transition-colors hover:text-foreground'

  return (
    <PageContainer className="py-8 sm:py-10">
      <Card>
        <CardContent className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <UserAvatar user={profile} className="size-16 text-base" />
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-[1.5rem] leading-tight md:text-[1.625rem]">
              {profile.display_name}
            </h1>
            <p className="text-sm text-muted-foreground">@{profile.username}</p>
            {profile.bio && (
              <p className="mt-3 max-w-2xl text-sm whitespace-pre-line text-foreground/90">{profile.bio}</p>
            )}
            <SkillTags skills={profile.skills} className="mt-3" label="Skills" />
            {profile.interests.length > 0 && (
              <p className="mt-2 text-[0.8125rem] text-muted-foreground">
                Interested in {profile.interests.join(', ')}
              </p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-0 text-[0.8125rem]">
              <span className="inline-flex min-h-9 items-center gap-1.5 text-muted-foreground">
                <CalendarDays className="size-4" aria-hidden /> Joined {formatDate(profile.joined_at)}
              </span>
              {github && (
                <a href={github} target="_blank" rel="noopener noreferrer nofollow me" className={linkClass}>
                  <GithubMark /> GitHub
                </a>
              )}
              {portfolio && (
                <a
                  href={portfolio}
                  target="_blank"
                  rel="noopener noreferrer nofollow me"
                  className={linkClass}
                >
                  <Globe className="size-4" aria-hidden /> Portfolio
                </a>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <section aria-labelledby="stats-h" className="mt-6">
        <h2 id="stats-h" className="sr-only">
          Marketplace stats
        </h2>
        <StatGrid className="grid-cols-2 md:grid-cols-4">
          <StatTile label="Bounties created" value={formatNumber(s.bounties_created)} />
          <StatTile label="Bounties completed" value={formatNumber(s.bounties_completed_as_requester)} />
          <StatTile label="Contributions" value={formatNumber(s.contributions_completed)} />
          <StatTile label="Applications" value={formatNumber(s.applications_submitted)} />
          <StatTile label="Acceptance rate" value={formatPercent(s.acceptance_rate)} />
          <StatTile label="Approval rate" value={formatPercent(s.approval_rate)} />
          <StatTile label="Rewards received" value={<Xlm amount={s.total_rewards_received} />} />
          <StatTile label="Rewards paid" value={<Xlm amount={s.total_rewards_paid} />} />
        </StatGrid>
      </section>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Tabs defaultValue="bounties" className="min-w-0 gap-4">
          <TabsList>
            <TabsTrigger value="bounties" className="px-3">
              Created bounties
            </TabsTrigger>
            <TabsTrigger value="contributions" className="px-3">
              Contribution history
            </TabsTrigger>
          </TabsList>
          <TabsContent value="bounties">
            <CreatedBounties username={profile.username} />
          </TabsContent>
          <TabsContent value="contributions">
            <Contributions username={profile.username} />
          </TabsContent>
        </Tabs>

        <aside aria-label="Profile details" className="lg:pt-14">
          <Card className="gap-4">
            <CardHeader>
              <CardTitle>
                <h2 id="wallets-h">Wallets</h2>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Wallets profile={profile} />
            </CardContent>
          </Card>
        </aside>
      </div>
    </PageContainer>
  )
}
