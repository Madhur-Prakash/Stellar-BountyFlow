import {
  ArrowUpRight,
  CircleAlert,
  EyeOff,
  ExternalLink,
  GitPullRequest,
  Handshake,
  Settings2,
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
import { MetaList } from '@/components/bounty/MetaList'
import { ReportButton } from '@/components/bounty/ReportDialog'
import { RewardDisplay } from '@/components/bounty/RewardDisplay'
import { SkillTags } from '@/components/bounty/SkillTags'
import { SubmitWorkButton } from '@/components/bounty/SubmitWorkDialog'
import {
  ApplicationStatusBadge,
  PaymentStatusBadge,
  SubmissionStatusBadge,
} from '@/components/bounty/WorkStatusBadges'
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
import { CATEGORY_LABELS, DIFFICULTY_LABELS, formatDate, formatNumber } from '@/lib/format'
import NotFoundPage from '../NotFoundPage'

/** Markdown inside the document card: headings sized like the card's own section headings. */
const DOC_MARKDOWN =
  '[&_h1]:text-base [&_h1]:text-foreground [&_h2]:text-foreground [&_h2]:mt-8 [&_h2]:mb-2 [&_h2]:text-base [&_h3]:text-[0.9375rem]'

/** A titled block of the bounty document. */
function DocSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="mb-2 text-base font-semibold">
        {title}
      </h2>
      {children}
    </section>
  )
}

/** A block on the page canvas (transactions, activity), titled with a small mono label. */
function PageSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="pt-4">
      <h2 id={id} className="label-mono mb-3">
        {title}
      </h2>
      {children}
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
      <div className="rounded-lg border bg-surface/60 p-3 text-sm">
        <p className="font-medium">You’re assigned to this bounty.</p>
        {mine && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            Your submission (v{mine.version}): <SubmissionStatusBadge status={mine.status} />
            {mine.payment && <PaymentStatusBadge status={mine.payment.payment_status} />}
          </div>
        )}
        {needsRevision && mine.review_feedback && (
          <p className="mt-2 text-sm">
            <span className="text-muted-foreground">Requested changes: </span>
            {mine.review_feedback}
          </p>
        )}
      </div>
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
        <p className="flex items-center justify-between gap-2 rounded-lg border bg-surface/60 px-3 py-2.5 text-sm">
          Your application: <ApplicationStatusBadge status={viewer.application.status} />
        </p>
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
        : 'You can’t apply to this bounty.'
      : null
  return (
    <div className="space-y-2">
      <ApplyButton
        bountyId={bounty.id}
        bountyTitle={bounty.title}
        disabled={!!disabledReason}
        className="w-full"
      />
      {disabledReason && <p className="text-center text-xs text-muted-foreground">{disabledReason}</p>}
    </div>
  )
}

function BountyTransactions({ bountyId }: { bountyId: string }) {
  const { data, isPending, isError, error, refetch } = useBountyTransactions(bountyId)
  if (isPending) return <ListSkeleton rows={2} />
  if (isError) return <ErrorState error={error} title="Transactions unavailable" onRetry={() => refetch()} />
  if (data.length === 0) {
    return <EmptyState icon={ArrowUpRight} title="No transactions yet" className="py-8" />
  }
  return (
    // The table draws its own border; give it the card surface so it sits with the cards around it.
    <div className="[&>div:first-child]:overflow-hidden [&>div:first-child]:bg-card [&>div:first-child]:shadow-soft">
      <TransactionTable transactions={data} showBounty={false} caption="Bounty transactions" />
    </div>
  )
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

/** Summary card titles read as small mono labels above the figure. */
const LABEL_TITLE = 'font-mono text-[0.8125rem] font-normal tracking-[0.01em] text-muted-foreground'

function SummaryRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-9 items-center justify-between gap-3 py-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right tabular-nums">{children}</dd>
    </div>
  )
}

function BountyDetailView({ bounty }: { bounty: BountyDetail }) {
  const openPositions = Math.max(0, bounty.positions_available - bounty.positions_filled)
  const links = bounty.links.filter((l) => /^https?:\/\//i.test(l.url))

  return (
    <PageContainer className="pt-8 pb-16 sm:pt-12 sm:pb-20">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-x-10 xl:grid-cols-[minmax(0,1fr)_22rem]">
        {/* Header: first on every screen. */}
        <div className="min-w-0 lg:col-start-1 lg:row-start-1">
          <PageHeader
            breadcrumbs={[{ label: 'Marketplace', to: '/bounties' }, { label: bounty.title }]}
            title={bounty.title}
            description={bounty.short_description}
            actions={
              <>
                <BookmarkButton bountyId={bounty.id} bookmarked={bounty.is_bookmarked} variant="full" />
                <ReportButton bountyId={bounty.id} />
              </>
            }
            size="display"
            className="pb-4"
          />
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              {/* "Funded in escrow" already covers the FUNDED status; don't show the same fact twice. */}
              {bounty.status !== 'FUNDED' && <BountyStatusBadge status={bounty.status} />}
              <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
              {bounty.is_featured && <Badge variant="info">Featured</Badge>}
              {bounty.visibility === 'UNLISTED' && <Badge variant="muted">Unlisted</Badge>}
            </div>
            <MetaList className="text-[0.8125rem]">
              <span>{CATEGORY_LABELS[bounty.category]}</span>
              <span>{DIFFICULTY_LABELS[bounty.difficulty]}</span>
            </MetaList>
          </div>

          {bounty.is_hidden && (
            <Alert variant="warning" className="mt-5">
              <EyeOff />
              <AlertTitle>Hidden by moderation</AlertTitle>
              <AlertDescription>Only you and the moderators can see this bounty.</AlertDescription>
            </Alert>
          )}
          {bounty.status === 'CANCELLED' && (
            <Alert variant="warning" className="mt-5">
              <CircleAlert />
              <AlertTitle>This bounty was cancelled</AlertTitle>
              {bounty.cancel_reason && (
                <AlertDescription>Reason given: {bounty.cancel_reason}</AlertDescription>
              )}
            </Alert>
          )}
        </div>

        {/* Summary column: straight after the header on phones, a sticky column beside the document on desktop. */}
        <aside
          className="space-y-4 lg:sticky lg:top-20 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-start"
          aria-label="Bounty summary"
        >
          <Card className="gap-4">
            <CardHeader>
              <CardTitle className={LABEL_TITLE}>Reward</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <RewardDisplay
                rewardAmount={bounty.reward_amount}
                totalReward={bounty.total_reward}
                positions={bounty.positions_available}
                assetCode={bounty.reward_asset.code}
                size="lg"
              />
              <dl className="divide-y border-y text-sm">
                <SummaryRow label="Open positions">
                  {openPositions} of {bounty.positions_available}
                </SummaryRow>
                <SummaryRow label="Applicants">{formatNumber(bounty.applications_count)}</SummaryRow>
                <SummaryRow label="Applications close">
                  <DeadlineCountdown deadline={bounty.application_deadline} bare showSeconds />
                </SummaryRow>
                {bounty.completion_deadline && (
                  <SummaryRow label="Work due">{formatDate(bounty.completion_deadline)}</SummaryRow>
                )}
              </dl>
              <ApplyArea bounty={bounty} />
            </CardContent>
          </Card>

          <EscrowPanel bounty={bounty} />

          <DisputePanel bounty={bounty} />

          <Card className="gap-3">
            <CardHeader>
              <CardTitle className={LABEL_TITLE}>Requester</CardTitle>
            </CardHeader>
            <CardContent>
              <Link
                to={`/u/${bounty.requester.username}`}
                className="-m-1.5 flex items-center gap-3 rounded-lg p-1.5 transition-colors hover:bg-muted/60"
              >
                <UserAvatar user={bounty.requester} className="size-9" />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{bounty.requester.display_name}</div>
                  <div className="truncate text-xs text-muted-foreground">@{bounty.requester.username}</div>
                </div>
              </Link>
              <p className="mt-3 text-xs text-muted-foreground">
                Posted {formatDate(bounty.published_at ?? bounty.created_at)}
              </p>
            </CardContent>
          </Card>
        </aside>

        {/* The document. */}
        <div className="min-w-0 space-y-6 lg:col-start-1 lg:row-start-2">
          <Card className="py-4">
            <CardContent>
              <BountyTimeline bounty={bounty} />
            </CardContent>
          </Card>

          <Card className="sm:[--card-spacing:--spacing(7)]">
            <CardContent className="space-y-8">
              <section aria-labelledby="desc-h">
                <h2 id="desc-h" className="sr-only">
                  Description
                </h2>
                <SafeMarkdown className={DOC_MARKDOWN}>{bounty.description}</SafeMarkdown>
              </section>

              {bounty.required_skills.length > 0 && (
                <DocSection id="skills-h" title="Required skills">
                  <SkillTags skills={bounty.required_skills} label="Required skills" />
                  {bounty.tags.length > 0 && (
                    <p className="mt-3 text-[0.8125rem] text-muted-foreground">
                      Tags: {bounty.tags.map((t) => `#${t}`).join(' ')}
                    </p>
                  )}
                </DocSection>
              )}

              {bounty.eligibility_criteria && (
                <DocSection id="elig-h" title="Eligibility">
                  <SafeMarkdown className={DOC_MARKDOWN}>{bounty.eligibility_criteria}</SafeMarkdown>
                </DocSection>
              )}
              {bounty.submission_requirements && (
                <DocSection id="subreq-h" title="Submission requirements">
                  <SafeMarkdown className={DOC_MARKDOWN}>{bounty.submission_requirements}</SafeMarkdown>
                </DocSection>
              )}
              {bounty.acceptance_criteria && (
                <DocSection id="accept-h" title="Acceptance criteria">
                  <SafeMarkdown className={DOC_MARKDOWN}>{bounty.acceptance_criteria}</SafeMarkdown>
                </DocSection>
              )}

              {(bounty.repository_url || links.length > 0) && (
                <DocSection id="links-h" title="Links">
                  <ul className="space-y-0.5">
                    {bounty.repository_url && (
                      <li>
                        <ExternalAnchor href={bounty.repository_url}>Repository</ExternalAnchor>
                      </li>
                    )}
                    {links.map((l) => (
                      <li key={l.url}>
                        <ExternalAnchor href={l.url}>{l.label || l.url}</ExternalAnchor>
                      </li>
                    ))}
                  </ul>
                </DocSection>
              )}
            </CardContent>
          </Card>

          <PageSection id="tx-h" title="Verified transactions">
            <BountyTransactions bountyId={bounty.id} />
          </PageSection>

          <PageSection id="activity-h" title="Activity">
            <Card>
              <CardContent>
                <ActivityFeed bountyId={bounty.id} />
              </CardContent>
            </Card>
          </PageSection>
        </div>
      </div>
    </PageContainer>
  )
}

function ExternalAnchor({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="inline-flex min-h-9 max-w-full items-center gap-1.5 text-sm font-medium break-all text-primary-emphasis hover:underline"
    >
      {children} <ExternalLink className="size-3.5 shrink-0" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  )
}
