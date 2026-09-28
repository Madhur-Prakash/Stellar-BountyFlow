import {
  ArrowDownLeft,
  CircleSlash,
  ExternalLink,
  FileCheck2,
  GitPullRequest,
  LoaderCircle,
  PencilLine,
  Rocket,
  Wallet,
} from 'lucide-react'
import { useState } from 'react'
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
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { StatTile } from '@/components/common/StatTile'
import { EmptyState } from '@/components/layout/EmptyState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { CountUp } from '@/components/motion/CountUp'
import { Reveal } from '@/components/motion/Reveal'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { errorMessage, isEmailNotVerifiedError } from '@/lib/api/client'
import { chainApi, fundingApi } from '@/lib/api/endpoints'
import { useBounty, useCancelBounty, usePublishBounty } from '@/lib/api/queries/bounties'
import { useBountyTransactions } from '@/lib/api/queries/chain'
import type { BountyDetail } from '@/lib/api/types'
import { formatAmount } from '@/lib/money'

function Actions({ bounty }: { bounty: BountyDetail }) {
  const publish = usePublishBounty()
  const cancel = useCancelBounty()
  const [cancelOpen, setCancelOpen] = useState(false)
  const [publishError, setPublishError] = useState<unknown>(null)

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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {bounty.status === 'DRAFT' && (
          <Button
            disabled={publish.isPending}
            onClick={() => {
              setPublishError(null)
              publish.mutate(bounty.id, {
                onSuccess: () =>
                  toast.success('Published. Next: fund the escrow so contributors can see it’s real.'),
                onError: (e) => {
                  setPublishError(e)
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
            description={`Lock ${formatAmount(bounty.total_reward)} ${bounty.reward_asset.code} in the escrow contract for this bounty.`}
            prepare={(wallet_address) => fundingApi.prepare(bounty.id, { wallet_address })}
          />
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
        {canEdit && (
          <Button asChild variant="outline">
            <Link to={`/app/bounties/${bounty.id}/edit`}>
              <PencilLine /> Edit
            </Link>
          </Button>
        )}
        {bounty.status !== 'DRAFT' && (
          <Button asChild variant="outline">
            <Link to={`/bounties/${bounty.slug || bounty.id}`}>
              <ExternalLink /> Public page
            </Link>
          </Button>
        )}
        {canCancel && (
          <Button variant="ghost" className="text-destructive" onClick={() => setCancelOpen(true)}>
            <CircleSlash /> Cancel bounty
          </Button>
        )}
      </div>
      {isEmailNotVerifiedError(publishError) && <EmailNotVerifiedNotice />}
      {cancelling &&
        bounty.funding_status !== 'REFUNDED' &&
        bounty.escrow &&
        escrowState !== 'NOT_CREATED' && (
          <p className="max-w-2xl text-sm text-muted-foreground">
            Cancellation was requested
            {bounty.cancel_reason ? <> (“{bounty.cancel_reason}”)</> : null}. To get the escrowed reward back,{' '}
            {escrowState === 'FUNDED'
              ? 'first request cancellation on-chain, then refund the escrow.'
              : 'refund the escrow.'}
          </p>
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
    </div>
  )
}

/** A reward amount that counts up on first view and settles on the exact (full-precision) amount. */
function RewardFigure({ amount }: { amount: string }) {
  return (
    <CountUp
      value={Number(amount) || 0}
      format={(n) => formatAmount(n.toFixed(2), { maxDecimals: 2 })}
      display={formatAmount(amount)}
    />
  )
}

function Transactions({ bountyId }: { bountyId: string }) {
  const query = useBountyTransactions(bountyId)
  return (
    <QueryView
      query={query}
      skeleton="app-manage-bounty-transactions"
      isEmpty={(d) => d.length === 0}
      empty={{
        icon: Wallet,
        title: 'No transactions yet',
        description: 'Funding and payouts will appear here.',
      }}
    >
      {(txs) => <TransactionTable transactions={txs} showBounty={false} caption="Bounty transactions" />}
    </QueryView>
  )
}

export default function ManageBountyPage() {
  const { bountyId = '' } = useParams()
  const query = useBounty(bountyId)

  return (
    <div className="mx-auto max-w-7xl">
      <QueryView query={query} skeleton="app-manage-bounty" errorTitle="Could not load this bounty">
        {(bounty) =>
          !bounty.viewer?.is_owner && !bounty.viewer?.is_moderator ? (
            <EmptyState
              title="You don’t manage this bounty"
              description="Only the requester (and moderators) can open the management view."
              action={
                <Button asChild variant="outline">
                  <Link to={`/bounties/${bounty.slug || bounty.id}`}>View public page</Link>
                </Button>
              }
            />
          ) : (
            <>
              <PageHeader
                breadcrumbs={[{ label: 'My bounties', to: '/app/bounties' }, { label: bounty.title }]}
                title={bounty.title}
                description={bounty.short_description}
              />
              <div className="-mt-2 mb-6 flex flex-wrap gap-2">
                <BountyStatusBadge status={bounty.status} />
                <FundingStatusBadge status={bounty.funding_status} bountyStatus={bounty.status} />
              </div>
              <Actions bounty={bounty} />

              <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
                <div className="min-w-0 space-y-8">
                  <Card>
                    <CardContent>
                      <BountyTimeline bounty={bounty} />
                    </CardContent>
                  </Card>
                  <Reveal className="grid grid-cols-2 gap-3 md:grid-cols-4" y={14} stagger={0.05}>
                    <StatTile label="Applicants" value={<CountUp value={bounty.applications_count} />} />
                    <StatTile
                      label="Positions filled"
                      value={`${bounty.positions_filled} / ${bounty.positions_available}`}
                    />
                    <StatTile
                      label="Reward / position"
                      value={<RewardFigure amount={bounty.reward_amount} />}
                      hint={bounty.reward_asset.code}
                    />
                    <StatTile
                      label="Total reward"
                      value={<RewardFigure amount={bounty.total_reward} />}
                      hint={bounty.reward_asset.code}
                    />
                  </Reveal>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Button asChild variant="outline" size="lg" className="justify-start">
                      <Link to={`/app/bounties/${bounty.id}/applications`}>
                        <GitPullRequest /> Review applications
                      </Link>
                    </Button>
                    <Button asChild variant="outline" size="lg" className="justify-start">
                      <Link to={`/app/bounties/${bounty.id}/submissions`}>
                        <FileCheck2 /> Review submissions
                      </Link>
                    </Button>
                  </div>
                  <section aria-labelledby="tx-h">
                    <h2 id="tx-h" className="mb-3 font-semibold">
                      Transactions
                    </h2>
                    <Transactions bountyId={bounty.id} />
                  </section>
                </div>
                <aside className="space-y-4">
                  <EscrowPanel bounty={bounty} />
                  <DisputePanel bounty={bounty} />
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Activity</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ActivityFeed bountyId={bounty.id} />
                    </CardContent>
                  </Card>
                </aside>
              </div>
            </>
          )
        }
      </QueryView>
    </div>
  )
}
