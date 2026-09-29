import {
  ArrowDownLeft,
  CircleSlash,
  ExternalLink,
  LoaderCircle,
  PencilLine,
  Rocket,
  Wallet,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { ActivityFeed } from '@/components/bounty/ActivityFeed'
import { BountyStatusBadge } from '@/components/bounty/BountyStatusBadge'
import { BountyTimeline } from '@/components/bounty/BountyTimeline'
import { DisputePanel } from '@/components/bounty/DisputePanel'
import { EscrowPanel } from '@/components/bounty/EscrowPanel'
import { FundingStatusBadge } from '@/components/bounty/FundingStatusBadge'
import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { TransactionTable } from '@/components/chain/TransactionExplorer'
import { EmailNotVerifiedNotice } from '@/components/common/EmailNotVerifiedNotice'
import { MilestoneTimeline } from '@/components/escrow/MilestoneTimeline'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { EmptyState } from '@/components/layout/EmptyState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { errorMessage, isEmailNotVerifiedError } from '@/lib/api/client'
import { chainApi, fundingApi } from '@/lib/api/endpoints'
import { useBounty, useCancelBounty, usePublishBounty } from '@/lib/api/queries/bounties'
import { useBountyTransactions } from '@/lib/api/queries/chain'
import type { BountyDetail } from '@/lib/api/types'
import { formatWindow } from '@/lib/escrow'
import { CATEGORY_LABELS, DIFFICULTY_LABELS, formatDate, formatDateTime } from '@/lib/format'
import { formatMoney } from '@/lib/money'

import { FundingReadinessNotice } from '../assets/FundingReadinessNotice'
import { ManageBountyNav, ManageStats } from './ManageBountyNav'

/** Which lifecycle actions the requester can take right now. */
function actionState(bounty: BountyDetail) {
  const canEdit =
    bounty.status === 'DRAFT' || (bounty.status === 'OPEN' && bounty.funding_status === 'UNFUNDED')
  const canFund =
    ['OPEN', 'FUNDING_PENDING'].includes(bounty.status) &&
    ['UNFUNDED', 'PARTIALLY_FUNDED'].includes(bounty.funding_status)
  const canCancel = !['COMPLETED', 'CANCELLED', 'CANCEL_REQUESTED', 'EXPIRED', 'DISPUTED'].includes(
    bounty.status,
  )
  const cancelling = bounty.status === 'CANCEL_REQUESTED' || bounty.status === 'EXPIRED'
  const escrowState = bounty.escrow?.state
  // Refunds are two on-chain steps: request_cancel (escrow → CancelRequested), then refund.
  const canRequestCancelOnChain =
    cancelling && (escrowState === 'FUNDED' || escrowState === 'AWAITING_FUNDING')
  const canRefund =
    cancelling &&
    bounty.funding_status !== 'REFUNDED' &&
    (escrowState === 'CANCEL_REQUESTED' || escrowState === 'AWAITING_FUNDING')
  return { canEdit, canFund, canCancel, cancelling, escrowState, canRequestCancelOnChain, canRefund }
}

/** Header actions: the next lifecycle step first, then edit / public page, then cancel (kept apart). */
function Actions({ bounty, onPublishError }: { bounty: BountyDetail; onPublishError: (e: unknown) => void }) {
  const publish = usePublishBounty()
  const cancel = useCancelBounty()
  const [cancelOpen, setCancelOpen] = useState(false)
  const { canEdit, canFund, canCancel, escrowState, canRequestCancelOnChain, canRefund } = actionState(bounty)

  return (
    <>
      {canCancel && (
        <Button
          variant="ghost"
          className="text-destructive hover:text-destructive max-sm:order-last"
          onClick={() => setCancelOpen(true)}
        >
          <CircleSlash /> Cancel bounty
        </Button>
      )}
      {bounty.status !== 'DRAFT' && (
        <Button asChild variant="outline">
          <Link to={`/bounties/${bounty.slug || bounty.id}`}>
            <ExternalLink /> Public page
          </Link>
        </Button>
      )}
      {canEdit && (
        <Button asChild variant="outline">
          <Link to={`/app/bounties/${bounty.id}/edit`}>
            <PencilLine /> Edit
          </Link>
        </Button>
      )}
      {canRequestCancelOnChain && escrowState === 'FUNDED' && (
        <ChainActionButton
          label="Request cancellation on-chain"
          icon={CircleSlash}
          variant="outline"
          title="Request cancellation"
          description="Step 1 of 2: mark the escrow as cancel-requested in the contract. Contributors assigned on-chain must consent before their share can be refunded."
          prepare={(wallet_address) =>
            chainApi.prepare(bounty.id, { action: 'REQUEST_CANCEL', wallet_address })
          }
        />
      )}
      {canRefund && (
        <ChainActionButton
          label="Refund escrow"
          icon={ArrowDownLeft}
          variant="outline"
          title="Refund escrow"
          description={
            escrowState === 'CANCEL_REQUESTED'
              ? 'Step 2 of 2: return the escrowed reward to your wallet.'
              : 'Return the partial deposit to your wallet.'
          }
          prepare={(wallet_address) => chainApi.prepare(bounty.id, { action: 'REFUND', wallet_address })}
        />
      )}
      {bounty.status === 'DRAFT' && (
        <Button
          disabled={publish.isPending}
          onClick={() => {
            onPublishError(null)
            publish.mutate(bounty.id, {
              onSuccess: () => toast.success('Published. Fund the escrow next.'),
              onError: (e) => {
                onPublishError(e)
                if (!isEmailNotVerifiedError(e)) toast.error(errorMessage(e))
              },
            })
          }}
        >
          {publish.isPending ? <LoaderCircle className="animate-spin" /> : <Rocket />} Publish
        </Button>
      )}
      {canFund && (
        <ChainActionButton
          label="Fund escrow"
          icon={Wallet}
          title="Fund escrow"
          description={`Lock ${formatMoney(bounty.total_reward, bounty.reward_asset)} in the escrow contract for this bounty.`}
          prepare={(wallet_address) => fundingApi.prepare(bounty.id, { wallet_address })}
        />
      )}
      <ReasonDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Cancel this bounty?"
        description={
          bounty.funding_status === 'FUNDED'
            ? 'The bounty is funded, so this requests cancellation. You then request cancellation on-chain and refund the escrow to your wallet.'
            : bounty.funding_status === 'PARTIALLY_FUNDED'
              ? 'The bounty is partially funded, so this requests cancellation. You can then refund the deposit to your wallet.'
              : 'The bounty is not funded, so it will be cancelled immediately.'
        }
        confirmLabel="Cancel bounty"
        minLength={5}
        maxLength={1000}
        destructive
        pending={cancel.isPending}
        onConfirm={(reason) =>
          cancel.mutateAsync(
            { bountyId: bounty.id, reason },
            {
              onSuccess: () => toast.success('Cancellation recorded'),
              onError: (e) => toast.error(errorMessage(e)),
            },
          )
        }
      />
    </>
  )
}

function Transactions({ bountyId }: { bountyId: string }) {
  const query = useBountyTransactions(bountyId)
  return (
    <QueryView
      query={query}
      skeleton="app-manage-bounty-transactions"
      isEmpty={(d) => d.length === 0}
      empty={{ icon: Wallet, title: 'No transactions yet' }}
    >
      {(txs) => (
        // The table draws its own border; give it the card surface so it sits with the cards around it.
        <div className="[&>div:first-child]:overflow-hidden [&>div:first-child]:bg-card [&>div:first-child]:shadow-soft">
          <TransactionTable transactions={txs} showBounty={false} caption="Bounty transactions" />
        </div>
      )}
    </QueryView>
  )
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-9 items-center justify-between gap-3 py-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  )
}

function ManageView({ bounty }: { bounty: BountyDetail }) {
  const [publishError, setPublishError] = useState<unknown>(null)
  const { cancelling, escrowState, canFund } = actionState(bounty)

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: 'My bounties', to: '/app/bounties' }, { label: bounty.title }]}
        title={bounty.title}
        description={bounty.short_description}
        className="pb-4"
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          <BountyStatusBadge status={bounty.status} />
          <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
          {bounty.visibility === 'UNLISTED' && <Badge variant="muted">Unlisted</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          <Actions bounty={bounty} onPublishError={setPublishError} />
        </div>
      </div>

      {(isEmailNotVerifiedError(publishError) ||
        (cancelling &&
          bounty.funding_status !== 'REFUNDED' &&
          bounty.escrow &&
          escrowState !== 'NOT_CREATED')) && (
        <div className="mt-4 space-y-3">
          {isEmailNotVerifiedError(publishError) && <EmailNotVerifiedNotice />}
          {cancelling &&
            bounty.funding_status !== 'REFUNDED' &&
            bounty.escrow &&
            escrowState !== 'NOT_CREATED' && (
              <p className="max-w-2xl text-sm text-muted-foreground">
                Cancellation was requested
                {bounty.cancel_reason ? <> (“{bounty.cancel_reason}”)</> : null}. To get the escrowed reward
                back,{' '}
                {escrowState === 'FUNDED'
                  ? 'first request cancellation on-chain, then refund the escrow.'
                  : 'refund the escrow.'}
              </p>
            )}
        </div>
      )}

      {canFund && <FundingReadinessNotice bounty={bounty} className="mt-4 max-w-2xl" />}

      <ManageBountyNav bountyId={bounty.id} applicants={bounty.applications_count} className="mt-6" />

      <ManageStats bounty={bounty} className="mt-6" />

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <Card className="py-4">
            <CardContent>
              <BountyTimeline bounty={bounty} />
            </CardContent>
          </Card>

          {(bounty.milestones?.length ?? 0) > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-[0.9375rem] font-semibold">Milestones</CardTitle>
              </CardHeader>
              <CardContent>
                <MilestoneTimeline milestones={bounty.milestones!} assetCode={bounty.reward_asset.code} />
              </CardContent>
            </Card>
          )}

          <section aria-labelledby="tx-h">
            <h2 id="tx-h" className="mb-3 text-[0.9375rem] font-semibold">
              Transactions
            </h2>
            <Transactions bountyId={bounty.id} />
          </section>

          <section aria-labelledby="activity-h">
            <h2 id="activity-h" className="mb-3 text-[0.9375rem] font-semibold">
              Activity
            </h2>
            <Card>
              <CardContent>
                <ActivityFeed bountyId={bounty.id} />
              </CardContent>
            </Card>
          </section>
        </div>

        <aside className="space-y-4" aria-label="Escrow and details">
          <EscrowPanel bounty={bounty} />
          <DisputePanel bounty={bounty} />
          <Card className="gap-3">
            <CardHeader>
              <CardTitle className="font-mono text-[0.8125rem] font-normal tracking-[0.01em] text-muted-foreground">
                Details
              </CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="divide-y text-sm">
                <DetailRow label="Category">{CATEGORY_LABELS[bounty.category]}</DetailRow>
                <DetailRow label="Difficulty">{DIFFICULTY_LABELS[bounty.difficulty]}</DetailRow>
                <DetailRow label="Visibility">
                  {bounty.visibility === 'UNLISTED' ? 'Unlisted' : 'Public'}
                </DetailRow>
                <DetailRow label="Applications close">
                  {bounty.application_deadline ? formatDateTime(bounty.application_deadline) : 'No deadline'}
                </DetailRow>
                <DetailRow label="Work due">
                  {bounty.completion_deadline ? formatDateTime(bounty.completion_deadline) : 'No deadline'}
                </DetailRow>
                {bounty.review_window_seconds ? (
                  <DetailRow label="Review window">{formatWindow(bounty.review_window_seconds)}</DetailRow>
                ) : null}
                <DetailRow label="Created">{formatDate(bounty.created_at)}</DetailRow>
                {bounty.published_at && (
                  <DetailRow label="Published">{formatDate(bounty.published_at)}</DetailRow>
                )}
              </dl>
            </CardContent>
          </Card>
        </aside>
      </div>
    </>
  )
}

export default function ManageBountyPage() {
  const { bountyId = '' } = useParams()
  const query = useBounty(bountyId)

  return (
    <QueryView query={query} skeleton="app-manage-bounty" errorTitle="Could not load this bounty">
      {(bounty) =>
        !bounty.viewer?.is_owner && !bounty.viewer?.is_moderator ? (
          <EmptyState
            title="You don’t manage this bounty"
            description="Only the requester and moderators can manage it."
            action={
              <Button asChild variant="outline">
                <Link to={`/bounties/${bounty.slug || bounty.id}`}>View public page</Link>
              </Button>
            }
          />
        ) : (
          <ManageView bounty={bounty} />
        )
      }
    </QueryView>
  )
}
