import { Check, ExternalLink, GitPullRequest, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { SkillTags } from '@/components/bounty/SkillTags'
import { ApplicationStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { UserAvatar } from '@/components/common/UserAvatar'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { errorMessage, isApiError } from '@/lib/api/client'
import { chainApi } from '@/lib/api/endpoints'
import {
  useAcceptApplication,
  useBountyApplications,
  useRejectApplication,
} from '@/lib/api/queries/applications'
import { useBounty } from '@/lib/api/queries/bounties'
import { useOnchainAssignees } from '@/lib/api/queries/chain'
import { usePublicProfile } from '@/lib/api/queries/users'
import type { Application, ApplicationStatus } from '@/lib/api/types'
import { formatRelative } from '@/lib/format'

import { ApplicantTrustlineBadge } from '../assets/ApplicantTrustlineBadge'
import { ManageBountyNav, ManageStats } from './ManageBountyNav'

/** Accept errors about the contributor's wallet, shown on the card rather than as a toast. */
const RECEIVE_ERRORS = new Set(['contributor_wallet_missing', 'trustline_missing', 'trustline_unauthorized'])

/** Whether this accepted contributor is already assigned in the escrow contract. */
function useAssignedOnchain(app: Application, assignees: Set<string>, enabled: boolean): boolean | null {
  // The API reports the verified on-chain assignment directly; older responses fall back to inference from the
  // escrow's confirmed ASSIGN transactions and the contributor's public wallets.
  const serverKnows = typeof app.onchain_assigned === 'boolean'
  const { data: profile } = usePublicProfile(enabled && !serverKnows ? app.contributor.username : undefined)
  if (!enabled) return null
  if (serverKnows) return app.onchain_assigned ?? false
  if (!profile) return null
  return profile.wallets.some((w) => assignees.has(w.public_address))
}

function ApplicationCard({
  app,
  canAccept,
  canAssignOnChain,
  assignees,
}: {
  app: Application
  canAccept: boolean
  canAssignOnChain: boolean
  assignees: Set<string>
}) {
  const accept = useAcceptApplication()
  const assignedOnchain = useAssignedOnchain(app, assignees, app.status === 'ACCEPTED' && canAssignOnChain)
  const reject = useRejectApplication()
  const [dialog, setDialog] = useState<'accept' | 'reject' | null>(null)
  const [walletError, setWalletError] = useState<string | null>(null)
  const samples = app.work_samples.filter((u) => /^https?:\/\//i.test(u))
  const showAssigned = app.status === 'ACCEPTED' && assignedOnchain
  const showAssign =
    app.status === 'ACCEPTED' && !!app.assignment_id && canAssignOnChain && assignedOnchain === false
  const hasFooter = app.status === 'PENDING' || showAssigned || showAssign

  return (
    <li className="overflow-hidden rounded-xl border bg-card shadow-soft">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <Link
          to={`/u/${app.contributor.username}`}
          className="-m-1 flex min-w-0 items-center gap-3 rounded-lg p-1 transition-colors hover:bg-muted/60"
        >
          <UserAvatar user={app.contributor} className="size-9" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{app.contributor.display_name}</div>
            <div className="truncate text-xs text-muted-foreground">
              @{app.contributor.username}, applied {formatRelative(app.created_at)}
            </div>
          </div>
        </Link>
        <div className="flex flex-wrap items-center gap-1.5">
          <ApplicantTrustlineBadge
            bountyId={app.bounty_id}
            contributorId={app.contributor.id}
            enabled={app.status === 'PENDING' || app.status === 'ACCEPTED'}
          />
          <ApplicationStatusBadge status={app.status} />
        </div>
      </div>

      <div className="space-y-3 px-5 pt-3 pb-4">
        <p className="max-w-3xl text-sm leading-6 whitespace-pre-line">{app.cover_message}</p>
        {app.relevant_experience && (
          <div className="max-w-3xl text-sm">
            <p className="text-xs font-medium text-muted-foreground">Experience</p>
            <p className="mt-0.5 leading-6 whitespace-pre-line">{app.relevant_experience}</p>
          </div>
        )}
        {samples.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Work samples">
            {samples.map((u) => (
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
        <SkillTags skills={app.contributor.skills} label={`${app.contributor.display_name}’s skills`} />
        {app.review_note && <p className="text-xs text-muted-foreground">Your note: {app.review_note}</p>}
        {walletError && (
          <Alert variant="warning">
            <AlertDescription>{walletError}</AlertDescription>
          </Alert>
        )}
      </div>

      {hasFooter && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t bg-surface/50 px-5 py-3">
          {app.status === 'PENDING' && (
            <>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={!canAccept}
                  onClick={() => setDialog('accept')}
                  title={
                    canAccept ? undefined : 'Fund the escrow and keep a position open to accept applicants'
                  }
                >
                  <Check /> Accept
                </Button>
                <Button size="sm" variant="outline" onClick={() => setDialog('reject')}>
                  <X /> Reject
                </Button>
              </div>
              {!canAccept && (
                <p className="text-xs text-muted-foreground">
                  Accepting needs a funded bounty with an open position.
                </p>
              )}
            </>
          )}
          {showAssigned && (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
              <ShieldCheck className="size-3.5" aria-hidden /> Assigned on-chain
            </span>
          )}
          {showAssign && (
            <ChainActionButton
              size="sm"
              variant="outline"
              label="Record assignment on-chain"
              title="Assign contributor"
              description={`Assign ${app.contributor.display_name} to this bounty in the escrow contract.`}
              prepare={(wallet_address) =>
                chainApi.prepare(app.bounty_id, {
                  action: 'ASSIGN',
                  wallet_address,
                  assignment_id: app.assignment_id ?? undefined,
                })
              }
            />
          )}
        </div>
      )}

      <ReasonDialog
        open={dialog === 'accept'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Accept ${app.contributor.display_name}?`}
        description="They’ll be assigned to a position and notified. The contributor must have a verified wallet that can receive the reward asset."
        label="Note to the contributor"
        required={false}
        confirmLabel="Accept"
        pending={accept.isPending}
        onConfirm={(note) =>
          accept.mutateAsync(
            { id: app.id, note: note || undefined },
            {
              onSuccess: () => {
                setWalletError(null)
                toast.success('Applicant accepted')
              },
              onError: (e) => {
                if (isApiError(e) && RECEIVE_ERRORS.has(String(e.code))) setWalletError(errorMessage(e))
                else toast.error(errorMessage(e))
              },
            },
          )
        }
      />
      <ReasonDialog
        open={dialog === 'reject'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Reject ${app.contributor.display_name}?`}
        label="Note (visible to you only)"
        required={false}
        confirmLabel="Reject"
        destructive
        pending={reject.isPending}
        onConfirm={(note) =>
          reject.mutateAsync(
            { id: app.id, note: note || undefined },
            {
              onSuccess: () => toast.success('Application rejected'),
              onError: (e) => toast.error(errorMessage(e)),
            },
          )
        }
      />
    </li>
  )
}

export default function BountyApplicationsPage() {
  const { bountyId = '' } = useParams()
  const [status, setStatus] = useState<ApplicationStatus | 'ALL'>('PENDING')
  const [page, setPage] = useState(1)
  const bounty = useBounty(bountyId)
  const query = useBountyApplications(bountyId, {
    status: status === 'ALL' ? undefined : status,
    page,
    page_size: 20,
  })
  const b = bounty.data
  const canAccept =
    !!b &&
    ['FUNDED', 'IN_PROGRESS', 'UNDER_REVIEW'].includes(b.status) &&
    b.positions_filled < b.positions_available
  const escrowFunded = b?.escrow?.state === 'FUNDED'
  const { assignees } = useOnchainAssignees(escrowFunded ? bountyId : undefined)

  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: 'My bounties', to: '/app/bounties' },
          { label: b?.title ?? 'Bounty', to: `/app/bounties/${bountyId}` },
          { label: 'Applications' },
        ]}
        title="Applications"
        actions={
          b && b.status !== 'DRAFT' ? (
            <Button asChild variant="outline">
              <Link to={`/bounties/${b.slug || b.id}`}>
                <ExternalLink /> Public page
              </Link>
            </Button>
          ) : undefined
        }
        className="pb-4"
      />
      <ManageBountyNav bountyId={bountyId} applicants={b?.applications_count} />
      {b && <ManageStats bounty={b} className="mt-6" />}

      <Tabs
        value={status}
        onValueChange={(v) => {
          setStatus(v as ApplicationStatus | 'ALL')
          setPage(1)
        }}
        className="mt-6 gap-4"
      >
        <TabsList>
          <TabsTrigger value="PENDING" className="px-3">
            Pending
          </TabsTrigger>
          <TabsTrigger value="ACCEPTED" className="px-3">
            Accepted
          </TabsTrigger>
          <TabsTrigger value="REJECTED" className="px-3">
            Rejected
          </TabsTrigger>
          <TabsTrigger value="ALL" className="px-3">
            All
          </TabsTrigger>
        </TabsList>

        <TabsContent value={status}>
          <QueryView
            query={query}
            skeleton="app-bounty-applications"
            isEmpty={(d) => d.items.length === 0}
            empty={{
              icon: GitPullRequest,
              title: status === 'PENDING' ? 'No applications waiting' : 'No applications here',
            }}
          >
            {(data) => (
              <>
                <ul className="space-y-4">
                  {data.items.map((a) => (
                    <ApplicationCard
                      key={a.id}
                      app={a}
                      canAccept={canAccept}
                      canAssignOnChain={escrowFunded}
                      assignees={assignees}
                    />
                  ))}
                </ul>
                <PaginationBar
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  pageSize={data.page_size}
                  onPageChange={setPage}
                  itemLabel="applications"
                />
              </>
            )}
          </QueryView>
        </TabsContent>
      </Tabs>
    </div>
  )
}
