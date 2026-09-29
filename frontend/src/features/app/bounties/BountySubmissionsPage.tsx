import { Check, CircleDollarSign, ExternalLink, FileCheck2, RotateCcw, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { PaymentStatusBadge, SubmissionStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { BatchPayBar } from '@/components/escrow/BatchPayBar'
import { OnchainAnswerButtons } from '@/components/escrow/OnchainAnswer'
import { ReviewClock } from '@/components/escrow/ReviewClock'
import { TransactionExplorerCard } from '@/components/chain/TransactionExplorer'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { PullRequestList } from '@/components/github/PullRequestList'
import { UserAvatar } from '@/components/common/UserAvatar'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { SafeMarkdown } from '@/components/markdown/SafeMarkdown'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { errorMessage } from '@/lib/api/client'
import { chainApi, payoutsApi } from '@/lib/api/endpoints'
import { useBounty } from '@/lib/api/queries/bounties'
import { useEscrowConfig } from '@/lib/api/queries/escrow'
import {
  useApproveSubmission,
  useBountySubmissions,
  useRejectSubmission,
  useRequestRevision,
} from '@/lib/api/queries/submissions'
import type { Submission } from '@/lib/api/types'
import { formatRelative } from '@/lib/format'
import { formatAmount } from '@/lib/money'

import { ManageBountyNav, ManageStats } from './ManageBountyNav'

const REVIEWABLE = new Set(['SUBMITTED', 'RESUBMITTED'])
const PAYABLE = new Set(['CREATED', 'SIGNATURE_REQUIRED', 'FAILED'])

/** Approved and not paid yet: can go into a batch payout. */
function isPayable(s: Submission): boolean {
  return s.status === 'APPROVED' && !!s.payment && PAYABLE.has(s.payment.payment_status)
}

function SubmissionCard({
  s,
  isOwner,
  requireMerged = false,
  selectable = false,
  selected = false,
  onSelect,
}: {
  s: Submission
  isOwner: boolean
  requireMerged?: boolean
  selectable?: boolean
  selected?: boolean
  onSelect?: (checked: boolean) => void
}) {
  const approve = useApproveSubmission()
  const revise = useRequestRevision()
  const reject = useRejectSubmission()
  const [dialog, setDialog] = useState<'approve' | 'revise' | 'reject' | null>(null)
  const close = (o: boolean) => !o && setDialog(null)
  const onError = (e: unknown) => toast.error(errorMessage(e))
  const links = [s.evidence_url, ...s.evidence_links].filter(
    (u): u is string => !!u && /^https?:\/\//i.test(u),
  )
  const canReview = isOwner && REVIEWABLE.has(s.status)
  const canPay = isOwner && isPayable(s)
  // While the contract's review clock runs, a revision request or a rejection is signed on-chain.
  const clockRunning = s.onchain_review?.state === 'PENDING'

  return (
    <li className="overflow-hidden rounded-xl border bg-card shadow-soft">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="flex min-w-0 items-center gap-3">
          {selectable && (
            <Checkbox
              checked={selected}
              onCheckedChange={(v) => onSelect?.(v === true)}
              aria-label={`Select ${s.contributor.display_name}'s payout for a batch payment`}
            />
          )}
          <UserAvatar user={s.contributor} className="size-9" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{s.contributor.display_name}</div>
            <div className="text-xs text-muted-foreground">
              Version {s.version}, updated {formatRelative(s.updated_at)}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {s.milestone && (
            <Badge variant="muted">
              Milestone {s.milestone.position + 1}: {s.milestone.title}
            </Badge>
          )}
          <SubmissionStatusBadge status={s.status} />
          {s.payment && <PaymentStatusBadge status={s.payment.payment_status} />}
        </div>
      </div>

      <div className="space-y-3 px-5 pt-3 pb-4">
        {isOwner && s.onchain_review && <ReviewClock review={s.onchain_review} perspective="requester" />}
        <SafeMarkdown className="max-w-3xl text-sm leading-6">{s.description}</SafeMarkdown>
        {links.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Evidence links">
            {links.map((u) => (
              <li key={u}>
                <a
                  href={u}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors hover:bg-muted"
                >
                  {new URL(u).hostname}
                  <ExternalLink className="size-3 text-muted-foreground" aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              </li>
            ))}
          </ul>
        )}
        <PullRequestList
          submissionId={s.id}
          pullRequests={s.pull_requests ?? []}
          requireMerged={requireMerged}
          review={s.onchain_review ?? null}
          perspective="requester"
        />
        {s.review_feedback && (
          <p className="rounded-lg border bg-surface/60 px-3 py-2 text-sm">
            <span className="text-muted-foreground">Feedback: </span>
            {s.review_feedback}
          </p>
        )}
        {s.payment?.transaction && s.payment.transaction.status !== 'SIGNATURE_REQUIRED' && (
          <TransactionExplorerCard tx={s.payment.transaction} title="Payout transaction" />
        )}
      </div>

      {(canReview || canPay) && (
        <div className="flex flex-wrap items-center gap-2 border-t bg-surface/50 px-5 py-3">
          {canReview && (
            <>
              <Button size="sm" onClick={() => setDialog('approve')}>
                <Check /> Approve
              </Button>
              {clockRunning ? (
                s.onchain_review?.can_answer && <OnchainAnswerButtons submission={s} />
              ) : (
                <>
                  <Button size="sm" variant="outline" onClick={() => setDialog('revise')}>
                    <RotateCcw /> Request revision
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive sm:ml-auto"
                    onClick={() => setDialog('reject')}
                  >
                    <X /> Reject
                  </Button>
                </>
              )}
            </>
          )}
          {canPay && s.payment && s.milestone && (
            <ChainActionButton
              size="sm"
              icon={CircleDollarSign}
              label={`Pay milestone ${formatAmount(s.payment.amount)} ${s.payment.asset.code}`}
              title="Release milestone"
              description={`Pay ${s.contributor.display_name} ${formatAmount(s.payment.amount)} ${s.payment.asset.code} for “${s.milestone.title}”.`}
              prepare={(wallet_address) =>
                chainApi.prepare(s.bounty_id, {
                  action: 'MILESTONE_PAYOUT',
                  wallet_address,
                  submission_id: s.id,
                })
              }
            />
          )}
          {canPay && s.payment && !s.milestone && (
            <ChainActionButton
              size="sm"
              icon={CircleDollarSign}
              label={`Pay ${formatAmount(s.payment.amount)} ${s.payment.asset.code}`}
              title="Release payout"
              description={`Pay ${s.contributor.display_name} from escrow for this approved submission.`}
              prepare={(wallet_address) =>
                payoutsApi.prepare(s.bounty_id, { wallet_address, submission_id: s.id })
              }
            />
          )}
        </div>
      )}

      <ReasonDialog
        open={dialog === 'approve'}
        onOpenChange={close}
        title="Approve this submission?"
        description="This creates a payout record. You’ll then sign the payout from escrow."
        label="Feedback"
        required={false}
        confirmLabel="Approve"
        pending={approve.isPending}
        onConfirm={(feedback) =>
          approve.mutateAsync(
            { id: s.id, feedback: feedback || undefined },
            { onSuccess: () => toast.success('Submission approved'), onError },
          )
        }
      />
      <ReasonDialog
        open={dialog === 'revise'}
        onOpenChange={close}
        title="Request a revision"
        label="What needs to change?"
        minLength={10}
        confirmLabel="Request revision"
        pending={revise.isPending}
        onConfirm={(feedback) =>
          revise.mutateAsync(
            { id: s.id, feedback },
            { onSuccess: () => toast.success('Revision requested'), onError },
          )
        }
      />
      <ReasonDialog
        open={dialog === 'reject'}
        onOpenChange={close}
        title="Reject this submission?"
        label="Reason"
        minLength={10}
        confirmLabel="Reject"
        destructive
        pending={reject.isPending}
        onConfirm={(reason) =>
          reject.mutateAsync(
            { id: s.id, reason },
            { onSuccess: () => toast.success('Submission rejected'), onError },
          )
        }
      />
    </li>
  )
}

export default function BountySubmissionsPage() {
  const { bountyId = '' } = useParams()
  const [page, setPage] = useState(1)
  const bounty = useBounty(bountyId)
  const query = useBountySubmissions(bountyId, { page, page_size: 20 })
  const config = useEscrowConfig()
  const b = bounty.data
  const isOwner = !!b?.viewer?.is_owner
  // Batch payouts need the v2 escrow contract.
  const canBatch = isOwner && (b?.escrow?.contract_version ?? 1) >= 2 && b?.escrow?.state === 'FUNDED'
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set())
  const payable = (query.data?.items ?? []).filter(isPayable)
  const selected = payable.filter((s) => picked.has(s.id))
  const toggle = (id: string, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: 'My bounties', to: '/app/bounties' },
          { label: b?.title ?? 'Bounty', to: `/app/bounties/${bountyId}` },
          { label: 'Submissions' },
        ]}
        title="Submissions"
        actions={
          b && (
            <Button asChild variant="outline">
              <Link to={`/bounties/${b.slug || b.id}`}>View criteria</Link>
            </Button>
          )
        }
        className="pb-4"
      />
      <ManageBountyNav bountyId={bountyId} applicants={b?.applications_count} />
      {b && <ManageStats bounty={b} className="mt-6" />}

      <div className="mt-6">
        <QueryView
          query={query}
          skeleton="app-bounty-submissions"
          isEmpty={(d) => d.items.length === 0}
          empty={{ icon: FileCheck2, title: 'No submissions yet' }}
        >
          {(data) => (
            <>
              {canBatch && (
                <BatchPayBar
                  bountyId={bountyId}
                  selected={selected}
                  milestones={(b?.milestones?.length ?? 0) > 0}
                  maxBatch={config.data?.max_batch ?? 10}
                  onClear={() => setPicked(new Set())}
                  onConfirmed={() => setPicked(new Set())}
                />
              )}
              <ul className={canBatch && selected.length > 0 ? 'mt-4 space-y-4' : 'space-y-4'}>
                {data.items.map((s) => (
                  <SubmissionCard
                    key={s.id}
                    s={s}
                    isOwner={isOwner}
                    requireMerged={!!b?.require_merged_pr}
                    selectable={canBatch && payable.length > 1 && isPayable(s)}
                    selected={picked.has(s.id)}
                    onSelect={(on) => toggle(s.id, on)}
                  />
                ))}
              </ul>
              <PaginationBar
                page={data.page}
                pages={data.pages}
                total={data.total}
                pageSize={data.page_size}
                onPageChange={setPage}
                itemLabel="submissions"
              />
            </>
          )}
        </QueryView>
      </div>
    </div>
  )
}
