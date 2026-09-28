import { Check, CircleDollarSign, ExternalLink, FileCheck2, RotateCcw, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { PaymentStatusBadge, SubmissionStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { TransactionExplorerCard } from '@/components/chain/TransactionExplorer'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { UserAvatar } from '@/components/common/UserAvatar'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Reveal } from '@/components/motion/Reveal'
import { SafeMarkdown } from '@/components/markdown/SafeMarkdown'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api/client'
import { payoutsApi } from '@/lib/api/endpoints'
import { useBounty } from '@/lib/api/queries/bounties'
import {
  useApproveSubmission,
  useBountySubmissions,
  useRejectSubmission,
  useRequestRevision,
} from '@/lib/api/queries/submissions'
import type { Submission } from '@/lib/api/types'
import { formatRelative } from '@/lib/format'
import { formatAmount } from '@/lib/money'

const REVIEWABLE = new Set(['SUBMITTED', 'RESUBMITTED'])
const PAYABLE = new Set(['CREATED', 'SIGNATURE_REQUIRED', 'FAILED'])

function SubmissionCard({ s, isOwner }: { s: Submission; isOwner: boolean }) {
  const approve = useApproveSubmission()
  const revise = useRequestRevision()
  const reject = useRejectSubmission()
  const [dialog, setDialog] = useState<'approve' | 'revise' | 'reject' | null>(null)
  const close = (o: boolean) => !o && setDialog(null)
  const onError = (e: unknown) => toast.error(errorMessage(e))

  return (
    <li className="rounded-xl border bg-card p-5 shadow-soft">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <UserAvatar user={s.contributor} className="size-10" />
          <div>
            <div className="font-medium">{s.contributor.display_name}</div>
            <div className="text-sm text-muted-foreground">
              Version {s.version}, updated {formatRelative(s.updated_at)}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <SubmissionStatusBadge status={s.status} />
          {s.payment && <PaymentStatusBadge status={s.payment.payment_status} />}
        </div>
      </div>
      <SafeMarkdown className="mt-4">{s.description}</SafeMarkdown>
      {(s.evidence_url || s.evidence_links.length > 0) && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {[s.evidence_url, ...s.evidence_links]
            .filter((u): u is string => !!u && /^https?:\/\//i.test(u))
            .map((u) => (
              <li key={u}>
                <a
                  href={u}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="inline-flex min-h-9 items-center gap-1 rounded-md border px-2 text-xs hover:bg-muted"
                >
                  {new URL(u).hostname} <ExternalLink className="size-3" aria-hidden />
                </a>
              </li>
            ))}
        </ul>
      )}
      {s.review_feedback && (
        <p className="mt-3 text-sm text-muted-foreground">Feedback: {s.review_feedback}</p>
      )}

      {isOwner && (
        <div className="mt-4 flex flex-wrap gap-2">
          {REVIEWABLE.has(s.status) && (
            <>
              <Button size="sm" onClick={() => setDialog('approve')}>
                <Check /> Approve
              </Button>
              <Button size="sm" variant="outline" onClick={() => setDialog('revise')}>
                <RotateCcw /> Request revision
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive"
                onClick={() => setDialog('reject')}
              >
                <X /> Reject
              </Button>
            </>
          )}
          {s.status === 'APPROVED' && s.payment && PAYABLE.has(s.payment.payment_status) && (
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
      {s.payment?.transaction && s.payment.transaction.status !== 'SIGNATURE_REQUIRED' && (
        <TransactionExplorerCard tx={s.payment.transaction} title="Payout transaction" className="mt-4" />
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
  const isOwner = !!bounty.data?.viewer?.is_owner

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        breadcrumbs={[
          { label: 'My bounties', to: '/app/bounties' },
          { label: bounty.data?.title ?? 'Bounty', to: `/app/bounties/${bountyId}` },
          { label: 'Submissions' },
        ]}
        title="Submissions"
        description="Review delivered work against your acceptance criteria, then release payouts from escrow."
        actions={
          bounty.data && (
            <Button asChild variant="outline">
              <Link to={`/bounties/${bounty.data.slug || bounty.data.id}`}>View criteria</Link>
            </Button>
          )
        }
      />
      <QueryView
        query={query}
        skeleton="app-bounty-submissions"
        isEmpty={(d) => d.items.length === 0}
        empty={{
          icon: FileCheck2,
          title: 'No submissions yet',
          description: 'Assigned contributors’ work will appear here for review.',
        }}
      >
        {(data) => (
          <>
            <Reveal as="ul" className="space-y-4" deps={[data.items.map((s) => s.id).join()]}>
              {data.items.map((s) => (
                <SubmissionCard key={s.id} s={s} isOwner={isOwner} />
              ))}
            </Reveal>
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
  )
}
