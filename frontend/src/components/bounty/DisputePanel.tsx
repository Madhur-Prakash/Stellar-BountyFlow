import { Gavel, LoaderCircle, Lock, Paperclip, Scale } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { ChainActionButton } from '@/components/chain/ChainActionButton'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { chainApi } from '@/lib/api/endpoints'
import { useBountyApplications } from '@/lib/api/queries/applications'
import { useOnchainAssignees } from '@/lib/api/queries/chain'
import { useAddDisputeEvidence, useMyDisputes, useRaiseDispute } from '@/lib/api/queries/disputes'
import { usePublicProfile } from '@/lib/api/queries/users'
import { useWallets } from '@/lib/api/queries/wallets'
import type { BountyDetail, Dispute } from '@/lib/api/types'
import { DISPUTE_STATUS_LABELS, formatRelative } from '@/lib/format'

/** Bounty statuses in which the API accepts a new dispute. */
const DISPUTABLE_STATUSES = new Set(['IN_PROGRESS', 'UNDER_REVIEW', 'CANCEL_REQUESTED'])
const OPEN = new Set(['OPEN', 'UNDER_REVIEW'])

const RESOLUTION_LABELS: Record<string, string> = {
  RELEASE_TO_CONTRIBUTOR: 'Release the reward to the contributor',
  REFUND_TO_REQUESTER: 'Refund the requester',
  DISMISSED: 'Dismissed',
}

const isHttpUrl = (s: string) => {
  try {
    const u = new URL(s)
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}

function TextAndUrlDialog({
  open,
  onOpenChange,
  title,
  description,
  textLabel,
  minLength,
  confirmLabel,
  pending,
  onConfirm,
  children,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  description: string
  textLabel: string
  minLength: number
  confirmLabel: string
  pending: boolean
  onConfirm: (text: string, url: string | null) => Promise<unknown>
  children?: ReactNode
}) {
  const ids = { text: useId(), url: useId() }
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [touched, setTouched] = useState(false)
  const textErr = text.trim().length < minLength ? `Write at least ${minLength} characters.` : null
  const urlErr = url.trim() && !isHttpUrl(url.trim()) ? 'Use a full http(s) URL.' : null

  const close = (o: boolean) => {
    if (pending) return
    if (!o) {
      setText('')
      setUrl('')
      setTouched(false)
    }
    onOpenChange(o)
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={async (e) => {
            e.preventDefault()
            setTouched(true)
            if (textErr || urlErr || pending) return
            try {
              await onConfirm(text.trim(), url.trim() || null)
              close(false)
            } catch {
              /* surfaced by the caller */
            }
          }}
        >
          {children}
          <div className="space-y-2">
            <Label htmlFor={ids.text}>{textLabel}</Label>
            <Textarea
              id={ids.text}
              rows={5}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={touched && !!textErr}
              aria-describedby={touched && textErr ? `${ids.text}-err` : undefined}
            />
            {touched && textErr && (
              <p id={`${ids.text}-err`} role="alert" className="text-sm text-destructive">
                {textErr}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor={ids.url}>
              Evidence link <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id={ids.url}
              type="url"
              inputMode="url"
              placeholder="https://…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              aria-invalid={!!urlErr}
              aria-describedby={urlErr ? `${ids.url}-err` : undefined}
            />
            {urlErr && (
              <p id={`${ids.url}-err`} role="alert" className="text-sm text-destructive">
                {urlErr}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <LoaderCircle className="animate-spin" />}
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RaiseDisputeButton({ bounty }: { bounty: BountyDetail }) {
  const raise = useRaiseDispute(bounty.id)
  const [open, setOpen] = useState(false)
  const isOwner = !!bounty.viewer?.is_owner
  const accepted = useBountyApplications(isOwner ? bounty.id : undefined, {
    status: 'ACCEPTED',
    page_size: 50,
  })
  const contributors = (accepted.data?.items ?? []).map((a) => a.contributor)
  const [contributorId, setContributorId] = useState<string>('')
  const selectId = useId()
  const needsChoice = isOwner && contributors.length > 1

  return (
    <>
      <Button variant="outline" className="w-full" onClick={() => setOpen(true)}>
        <Scale /> Raise a dispute
      </Button>
      <TextAndUrlDialog
        open={open}
        onOpenChange={setOpen}
        title="Raise a dispute"
        description="A moderator reviews both sides. Reviews and payouts pause until it’s resolved."
        textLabel="What went wrong?"
        minLength={20}
        confirmLabel="Raise dispute"
        pending={raise.isPending}
        onConfirm={async (reason, url) => {
          if (needsChoice && !contributorId) {
            toast.error('Choose which contributor the dispute concerns.')
            throw new Error('contributor required')
          }
          try {
            await raise.mutateAsync({
              reason,
              evidence_url: url,
              contributor_id: needsChoice ? contributorId : undefined,
            })
            toast.success('Dispute raised. A moderator will review it.')
          } catch (e) {
            toast.error(errorMessage(e))
            throw e
          }
        }}
      >
        {needsChoice && (
          <div className="space-y-2">
            <Label htmlFor={selectId}>Contributor</Label>
            <Select value={contributorId} onValueChange={setContributorId}>
              <SelectTrigger id={selectId} className="w-full">
                <SelectValue placeholder="Choose a contributor" />
              </SelectTrigger>
              <SelectContent>
                {contributors.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.display_name} (@{c.username})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </TextAndUrlDialog>
    </>
  )
}

function AddEvidenceButton({ dispute }: { dispute: Dispute }) {
  const add = useAddDisputeEvidence()
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <Paperclip /> Add evidence
      </Button>
      <TextAndUrlDialog
        open={open}
        onOpenChange={setOpen}
        title="Add evidence"
        description="The other party and the moderators can see it."
        textLabel="Description"
        minLength={5}
        confirmLabel="Add evidence"
        pending={add.isPending}
        onConfirm={async (description, url) => {
          try {
            await add.mutateAsync({ id: dispute.id, body: { description, url } })
            toast.success('Evidence added')
          } catch (e) {
            toast.error(errorMessage(e))
            throw e
          }
        }}
      />
    </>
  )
}

/**
 * Dispute status and actions for the two parties of a bounty (the requester
 * and the assigned contributor). Hidden for everyone else.
 */
export function DisputePanel({ bounty }: { bounty: BountyDetail }) {
  const viewer = bounty.viewer
  // Accepted contributors stay parties after their assignment ends, so they can see the outcome.
  const isParty =
    !!viewer && (viewer.is_owner || viewer.is_assigned || viewer.application?.status === 'ACCEPTED')
  const { data: disputes } = useMyDisputes(isParty)
  const forBounty = (disputes ?? []).filter((d) => d.bounty.id === bounty.id)
  const active = forBounty.find((d) => OPEN.has(d.status)) ?? null
  const latest = active ?? forBounty[0] ?? null
  const escrowState = bounty.escrow?.state
  const freezable =
    !!active &&
    !active.escrow_frozen_onchain &&
    (escrowState === 'FUNDED' || escrowState === 'CANCEL_REQUESTED')

  // RAISE_DISPUTE needs the disputed contributor to be assigned on-chain (ASSIGN confirmed).
  const { assignees } = useOnchainAssignees(freezable ? bounty.id : undefined)
  const isOwner = !!viewer?.is_owner
  const { data: myWallets } = useWallets(freezable && !isOwner)
  const { data: contributorProfile } = usePublicProfile(
    freezable && isOwner ? active?.contributor?.username : undefined,
  )
  const contributorAddresses = isOwner
    ? (contributorProfile?.wallets ?? []).map((w) => w.public_address)
    : (myWallets ?? []).map((w) => w.public_address)
  const assignedOnchain = contributorAddresses.some((a) => assignees.has(a))

  if (!isParty) return null
  const canRaise = !active && DISPUTABLE_STATUSES.has(bounty.status)
  const canFreeze = freezable && assignedOnchain

  if (!latest && !canRaise) return null

  return (
    <Card className="gap-3" role="region" aria-labelledby="dispute-h">
      <CardHeader>
        <CardTitle
          id="dispute-h"
          className="flex items-center gap-2 font-mono text-[0.8125rem] font-normal tracking-[0.01em] text-muted-foreground"
        >
          <Gavel className="size-4 text-muted-foreground" aria-hidden /> Dispute
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {latest ? (
          <div className="space-y-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={OPEN.has(latest.status) ? 'warning' : 'muted'}>
                {DISPUTE_STATUS_LABELS[latest.status]}
              </Badge>
              {latest.escrow_frozen_onchain && (
                <Badge variant="info">
                  <Lock aria-hidden /> Escrow frozen
                </Badge>
              )}
              <span className="text-xs text-muted-foreground">
                Raised {formatRelative(latest.created_at)}
              </span>
            </div>
            <p className="line-clamp-4 text-muted-foreground">{latest.reason}</p>
            {latest.resolution && (
              <p>
                <span className="text-muted-foreground">Decision: </span>
                <span className="font-medium">
                  {RESOLUTION_LABELS[latest.resolution] ?? latest.resolution}
                </span>
              </p>
            )}
            {latest.requires_onchain_execution && (
              <Alert variant="info">
                <AlertTitle>Waiting for the arbiter</AlertTitle>
                <AlertDescription>
                  The escrow’s arbiter wallet must sign the decision before any funds move.
                </AlertDescription>
              </Alert>
            )}
            {active && (
              <div className="flex flex-wrap gap-2">
                <AddEvidenceButton dispute={active} />
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            If you can’t agree on the work, a moderator decides. Payouts pause while a dispute is open.
          </p>
        )}
        {freezable && !assignedOnchain && (
          <p className="text-xs text-muted-foreground">
            The contributor is not assigned on-chain, so the escrow itself can’t be frozen. The open dispute
            still pauses reviews and payouts here, and a moderator will decide.
          </p>
        )}
        {canFreeze && active && (
          <ChainActionButton
            variant="outline"
            className="w-full"
            icon={Lock}
            label="Freeze escrow on-chain"
            title="Freeze escrow"
            description="Lock the escrow in the contract while the dispute is reviewed. Only the arbiter can then route the reward."
            prepare={(wallet_address) =>
              chainApi.prepare(bounty.id, { action: 'RAISE_DISPUTE', wallet_address, dispute_id: active.id })
            }
          />
        )}
        {canRaise && <RaiseDisputeButton bounty={bounty} />}
      </CardContent>
    </Card>
  )
}
