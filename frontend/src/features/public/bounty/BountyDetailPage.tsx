import {
  ArrowUpRight,
  BriefcaseBusiness,
  CircleAlert,
  EyeOff,
  ExternalLink,
  GitPullRequest,
  Handshake,
  Settings2,
  Users,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'

import { ActivityFeed } from '@/components/bounty/ActivityFeed'
import { ApplyButton } from '@/components/bounty/ApplyDialog'
import { BookmarkButton } from '@/components/bounty/BookmarkButton'
import { BountyStatusBadge } from '@/components/bounty/BountyStatusBadge'
import { BountyTimeline } from '@/components/bounty/BountyTimeline'
import { DeadlineCountdown } from '@/components/bounty/DeadlineCountdown'
import { DisputePanel } from '@/components/bounty/DisputePanel'
import { EscrowPanel } from '@/components/bounty/EscrowPanel'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { ReportButton } from '@/components/bounty/ReportDialog'
import { RewardDisplay } from '@/components/bounty/RewardDisplay'
import { SkillTags } from '@/components/bounty/SkillTags'
import { SubmitWorkButton } from '@/components/bounty/SubmitWorkDialog'
import { PaymentStatusBadge, SubmissionStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { TransactionTable } from '@/components/chain/TransactionExplorer'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { ListSkeleton, LoadingState } from '@/components/layout/LoadingState'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { SafeMarkdown } from '@/components/markdown/SafeMarkdown'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { isApiError } from '@/lib/api/client'
import { chainApi } from '@/lib/api/endpoints'
import { useBounty } from '@/lib/api/queries/bounties'
import { useBountyTransactions } from '@/lib/api/queries/chain'
import { useBountySubmissions } from '@/lib/api/queries/submissions'
import type { BountyDetail } from '@/lib/api/types'
import {
  APPLICATION_STATUS_LABELS,
  CATEGORY_LABELS,
  DIFFICULTY_LABELS,
  formatDate,
  formatNumber,
} from '@/lib/format'
import NotFoundPage from '../NotFoundPage'

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="border-t pt-8">
      <h2 id={id} className="text-lg font-semibold">
        {title}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  )
}

/** Assigned contributor: deliver work, follow the review, and consent to cancellations. */
function ContributorWorkArea({ bounty }: { bounty: BountyDetail }) {
  const viewer = bounty.viewer!
  const { data } = useBountySubmissions(bounty.id, { page_size: 20 })
  const mine = data?.items[0] ?? null
  const needsRevision = mine?.status === 'REVISION_REQUESTED'
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm">
        <span className="font-medium">You’re assigned to this bounty.</span>
        {mine && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            Your submission (v{mine.version}): <SubmissionStatusBadge status={mine.status} />
            {mine.payment && <PaymentStatusBadge status={mine.payment.payment_status} />}
          </div>
        )}
      </div>
      {needsRevision && mine.review_feedback && (
        <p className="text-sm">
          <span className="text-muted-foreground">Requested changes: </span>
          {mine.review_feedback}
        </p>
      )}
      {viewer.can_submit && (
        <SubmitWorkButton bountyId={bounty.id} bountyTitle={bounty.title} className="w-full" />
      )}
      {needsRevision && (
        <SubmitWorkButton
          bountyId={bounty.id}
          bountyTitle={bounty.title}
          submission={mine}
          className="w-full"
        />
      )}
      {bounty.escrow?.state === 'CANCEL_REQUESTED' && (
        <ChainActionButton
          variant="outline"
          className="w-full"
          icon={Handshake}
          label="Consent to cancellation"
          title="Consent to cancellation"
          description="The requester asked to cancel. Consenting releases your on-chain assignment so the escrow can be refunded."
          prepare={(wallet_address) =>
            chainApi.prepare(bounty.id, { action: 'CONSENT_CANCEL', wallet_address })
          }
        />
      )}
      <Button asChild variant="outline" className="w-full">
        <Link to="/app/submissions">
          <GitPullRequest /> My submissions
        </Link>
      </Button>
    </div>
  )
}

function ApplyArea({ bounty }: { bounty: BountyDetail }) {
  const viewer = bounty.viewer
  if (viewer?.is_assigned && !viewer.is_owner) return <ContributorWorkArea bounty={bounty} />
  if (viewer?.is_owner) {
    return (
      <Button asChild size="lg" className="w-full">
        <Link to={`/app/bounties/${bounty.id}`}>
          <Settings2 /> Manage bounty
        </Link>
      </Button>
    )
  }
  if (viewer?.application) {
    return (
      <div className="space-y-2">
        <div className="rounded-lg border p-3 text-sm">
          Your application:{' '}
          <span className="font-medium">{APPLICATION_STATUS_LABELS[viewer.application.status]}</span>
        </div>
        <Button asChild variant="outline" className="w-full">
          <Link to="/app/applications">View my applications</Link>
        </Button>
      </div>
    )
  }
  const openPositions = bounty.positions_available - bounty.positions_filled
  const disabledReason =
    viewer && !viewer.can_apply
      ? openPositions <= 0
        ? 'All positions are filled.'
        : 'Applications are not open for your account on this bounty.'
      : null
  return (
    <div className="space-y-2">
      <ApplyButton
        bountyId={bounty.id}
        bountyTitle={bounty.title}
        disabled={!!disabledReason}
        className="w-full"
      />
      {disabledReason && <p className="text-xs text-muted-foreground">{disabledReason}</p>}
    </div>
  )
}

function BountyTransactions({ bountyId }: { bountyId: string }) {
  const { data, isPending, isError, error, refetch } = useBountyTransactions(bountyId)
  if (isPending) return <ListSkeleton rows={2} />
  if (isError) return <ErrorState error={error} title="Transactions unavailable" onRetry={() => refetch()} />
  if (data.length === 0) {
    return (
      <EmptyState
        icon={ArrowUpRight}
        title="No transactions yet"
        description="Funding, assignments, and payouts for this bounty will be listed here with their Stellar hashes."
      />
    )
  }
  return <TransactionTable transactions={data} showBounty={false} caption="Bounty transactions" />
}

export default function BountyDetailPage() {
  const { bountyId } = useParams()
  const { data: bounty, isPending, isError, error, refetch } = useBounty(bountyId)

  if (isError) {
    if (isApiError(error) && error.status === 404) return <NotFoundPage />
    return (
      <PageContainer className="py-16">
        <ErrorState error={error} title="Could not load this bounty" onRetry={() => refetch()} />
      </PageContainer>
    )
  }

  return (
    <Bones
      name="bounty-detail"
      loading={isPending}
      fallback={<LoadingState label="Loading bounty" className="min-h-[60vh]" />}
    >
      {bounty && <BountyDetailView bounty={bounty} />}
    </Bones>
  )
}

function BountyDetailView({ bounty }: { bounty: BountyDetail }) {
  const openPositions = Math.max(0, bounty.positions_available - bounty.positions_filled)

  return (
    <PageContainer className="py-10 sm:py-14">
      <PageHeader
        breadcrumbs={[{ label: 'Marketplace', to: '/bounties' }, { label: bounty.title }]}
        eyebrow={
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>{CATEGORY_LABELS[bounty.category]}</span>
            <span className="text-muted-foreground">{DIFFICULTY_LABELS[bounty.difficulty]}</span>
          </span>
        }
        title={bounty.title}
        description={bounty.short_description}
        actions={
          <>
            <BookmarkButton bountyId={bounty.id} bookmarked={bounty.is_bookmarked} variant="full" />
            <ReportButton bountyId={bounty.id} />
          </>
        }
      />

      <div className="-mt-2 mb-8 flex flex-wrap items-center gap-2">
        {/* "Funded in escrow" already covers the FUNDED status; don't show the same fact twice. */}
        {bounty.status !== 'FUNDED' && <BountyStatusBadge status={bounty.status} />}
        <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
        {bounty.is_featured && <Badge variant="info">Featured</Badge>}
        {bounty.visibility === 'UNLISTED' && <Badge variant="muted">Unlisted</Badge>}
      </div>

      {bounty.is_hidden && (
        <Alert variant="warning" className="mb-6">
          <EyeOff />
          <AlertTitle>Hidden by moderation</AlertTitle>
          <AlertDescription>
            This bounty is not visible in the marketplace. You can see it because you own or moderate it.
          </AlertDescription>
        </Alert>
      )}
      {bounty.status === 'CANCELLED' && (
        <Alert variant="warning" className="mb-6">
          <CircleAlert />
          <AlertTitle>This bounty was cancelled</AlertTitle>
          {bounty.cancel_reason && <AlertDescription>Reason given: {bounty.cancel_reason}</AlertDescription>}
        </Alert>
      )}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-8">
          <Card>
            <CardContent>
              <BountyTimeline bounty={bounty} />
            </CardContent>
          </Card>

          <section aria-labelledby="desc-h">
            <h2 id="desc-h" className="sr-only">
              Description
            </h2>
            <SafeMarkdown>{bounty.description}</SafeMarkdown>
          </section>

          {bounty.required_skills.length > 0 && (
            <Section id="skills-h" title="Required skills">
              <SkillTags skills={bounty.required_skills} label="Required skills" />
              {bounty.tags.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                  Tags:
                  {bounty.tags.map((t) => (
                    <span key={t}>#{t}</span>
                  ))}
                </div>
              )}
            </Section>
          )}

          {bounty.eligibility_criteria && (
            <Section id="elig-h" title="Eligibility">
              <SafeMarkdown>{bounty.eligibility_criteria}</SafeMarkdown>
            </Section>
          )}
          {bounty.submission_requirements && (
            <Section id="subreq-h" title="Submission requirements">
              <SafeMarkdown>{bounty.submission_requirements}</SafeMarkdown>
            </Section>
          )}
          {bounty.acceptance_criteria && (
            <Section id="accept-h" title="Acceptance criteria">
              <SafeMarkdown>{bounty.acceptance_criteria}</SafeMarkdown>
            </Section>
          )}

          {(bounty.repository_url || bounty.links.length > 0) && (
            <Section id="links-h" title="Links">
              <ul className="space-y-1">
                {bounty.repository_url && (
                  <li>
                    <a
                      href={bounty.repository_url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="inline-flex min-h-9 items-center gap-1.5 text-sm text-primary-emphasis hover:underline"
                    >
                      Repository <ExternalLink className="size-3.5" aria-hidden />
                    </a>
                  </li>
                )}
                {bounty.links
                  .filter((l) => /^https?:\/\//i.test(l.url))
                  .map((l) => (
                    <li key={l.url}>
                      <a
                        href={l.url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="inline-flex min-h-9 items-center gap-1.5 text-sm text-primary-emphasis hover:underline"
                      >
                        {l.label || l.url} <ExternalLink className="size-3.5" aria-hidden />
                      </a>
                    </li>
                  ))}
              </ul>
            </Section>
          )}

          <Section id="tx-h" title="Verified transactions">
            <BountyTransactions bountyId={bounty.id} />
          </Section>

          <Section id="activity-h" title="Activity">
            <ActivityFeed bountyId={bounty.id} />
          </Section>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start" aria-label="Bounty summary">
          <Card className="gap-4">
            <CardHeader>
              <CardTitle className="text-sm font-normal text-muted-foreground">Reward</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <RewardDisplay
                rewardAmount={bounty.reward_amount}
                totalReward={bounty.total_reward}
                positions={bounty.positions_available}
                assetCode={bounty.reward_asset.code}
                size="lg"
              />
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg border p-3">
                  <dt className="text-xs text-muted-foreground">Open positions</dt>
                  <dd className="mt-1 font-medium tabular-nums">
                    {openPositions} / {bounty.positions_available}
                  </dd>
                </div>
                <div className="rounded-lg border p-3">
                  <dt className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Users className="size-3" aria-hidden /> Applicants
                  </dt>
                  <dd className="mt-1 font-medium tabular-nums">{formatNumber(bounty.applications_count)}</dd>
                </div>
              </dl>
              <div className="space-y-1.5">
                <DeadlineCountdown
                  deadline={bounty.application_deadline}
                  label="Applications close"
                  showSeconds
                />
                {bounty.completion_deadline && (
                  <p className="text-xs text-muted-foreground">
                    Work due {formatDate(bounty.completion_deadline)}
                  </p>
                )}
              </div>
              <ApplyArea bounty={bounty} />
            </CardContent>
          </Card>

          <EscrowPanel bounty={bounty} />

          <DisputePanel bounty={bounty} />

          <Card className="gap-3">
            <CardHeader>
              <CardTitle className="text-sm font-normal text-muted-foreground">Requester</CardTitle>
            </CardHeader>
            <CardContent>
              <Link
                to={`/u/${bounty.requester.username}`}
                className="flex items-center gap-3 rounded-lg p-1 hover:bg-muted/50"
              >
                <UserAvatar user={bounty.requester} className="size-10" />
                <div className="min-w-0">
                  <div className="truncate font-medium">{bounty.requester.display_name}</div>
                  <div className="truncate text-sm text-muted-foreground">@{bounty.requester.username}</div>
                </div>
              </Link>
              <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
                <BriefcaseBusiness className="size-3.5" aria-hidden /> Posted{' '}
                {formatDate(bounty.published_at ?? bounty.created_at)}
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </PageContainer>
  )
}
