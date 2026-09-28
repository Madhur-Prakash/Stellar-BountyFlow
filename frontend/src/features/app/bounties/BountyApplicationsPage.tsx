import { Check, ExternalLink, GitPullRequest, Link2, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

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

  return (
    <li className="rounded-xl border bg-card p-5 shadow-soft">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <Link to={`/u/${app.contributor.username}`} className="flex items-center gap-3 hover:underline">
          <UserAvatar user={app.contributor} className="size-10" />
          <div>
            <div className="font-medium">{app.contributor.display_name}</div>
            <div className="text-sm text-muted-foreground">
              @{app.contributor.username}, applied {formatRelative(app.created_at)}
            </div>
          </div>
        </Link>
        <ApplicationStatusBadge status={app.status} />
      </div>
      <p className="mt-4 text-sm whitespace-pre-line">{app.cover_message}</p>
      {app.relevant_experience && (
        <p className="mt-3 text-sm whitespace-pre-line text-muted-foreground">
          <span className="font-medium text-foreground">Experience: </span>
          {app.relevant_experience}
        </p>
      )}
      {app.work_samples.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {app.work_samples
            .filter((u) => /^https?:\/\//i.test(u))
            .map((u) => (
              <li key={u}>
                <a
                  href={u}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="inline-flex min-h-9 items-center gap-1 rounded-md border px-2 text-xs hover:bg-muted"
                >
                  <Link2 className="size-3" aria-hidden /> {new URL(u).hostname}
                  <ExternalLink className="size-3" aria-hidden />
                </a>
              </li>
            ))}
        </ul>
      )}
      {app.contributor.skills.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">Skills: {app.contributor.skills.join(', ')}</p>
      )}
      {app.review_note && <p className="mt-3 text-xs text-muted-foreground">Your note: {app.review_note}</p>}

      {walletError && (
        <Alert variant="warning" className="mt-4">
          <AlertDescription>{walletError}</AlertDescription>
        </Alert>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {app.status === 'PENDING' && (
          <>
            <Button
              size="sm"
              disabled={!canAccept}
              onClick={() => setDialog('accept')}
              title={canAccept ? undefined : 'Fund the escrow and keep a position open to accept applicants'}
            >
              <Check /> Accept
            </Button>
            <Button size="sm" variant="outline" onClick={() => setDialog('reject')}>
              <X /> Reject
            </Button>
          </>
        )}
        {app.status === 'ACCEPTED' && assignedOnchain && (
          <span className="inline-flex items-center gap-1.5 text-xs text-success">
            <ShieldCheck className="size-3.5" aria-hidden /> Assigned on-chain
          </span>
        )}
        {app.status === 'ACCEPTED' && app.assignment_id && canAssignOnChain && assignedOnchain === false && (
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
      {!canAccept && app.status === 'PENDING' && (
        <p className="mt-2 text-xs text-muted-foreground">
          Accepting requires a funded bounty with an open position.
        </p>
      )}

      <ReasonDialog
        open={dialog === 'accept'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Accept ${app.contributor.display_name}?`}
        description="They’ll be assigned to a position and notified. The contributor must have a verified wallet."
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
                if (isApiError(e) && e.code === 'contributor_wallet_missing') setWalletError(errorMessage(e))
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
    <div className="mx-auto max-w-4xl">
      <PageHeader
        breadcrumbs={[
          { label: 'My bounties', to: '/app/bounties' },
          { label: b?.title ?? 'Bounty', to: `/app/bounties/${bountyId}` },
          { label: 'Applications' },
        ]}
        title="Applications"
        description={b ? `${b.positions_filled} of ${b.positions_available} positions filled` : undefined}
      />
      <Tabs
        value={status}
        onValueChange={(v) => {
          setStatus(v as ApplicationStatus | 'ALL')
          setPage(1)
        }}
        className="mb-4"
      >
        <TabsList>
          <TabsTrigger value="PENDING">Pending</TabsTrigger>
          <TabsTrigger value="ACCEPTED">Accepted</TabsTrigger>
          <TabsTrigger value="REJECTED">Rejected</TabsTrigger>
          <TabsTrigger value="ALL">All</TabsTrigger>
        </TabsList>

        <TabsContent value={status}>
          <QueryView
            query={query}
            skeleton="app-bounty-applications"
            isEmpty={(d) => d.items.length === 0}
            empty={{
              icon: GitPullRequest,
              title: 'No applications here',
              description: 'New applications will show up in the Pending tab.',
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
