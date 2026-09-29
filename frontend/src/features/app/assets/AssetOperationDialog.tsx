import { CheckCircle2, CircleAlert, ExternalLink, LoaderCircle, RotateCw, Wallet } from 'lucide-react'
import { useState, type ComponentProps, type ReactNode } from 'react'
import { toast } from 'sonner'

import { MonoValue } from '@/components/common/MonoValue'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { AssetOperation, PreparedAssetOperation } from '@/lib/api/types'
import { formatDateTime } from '@/lib/format'
import { formatStroops } from '@/lib/money'
import { networkDisplayName } from '@/lib/stellar/explorer'
import { walletProviderName } from '@/lib/stellar/wallet'
import { cn } from '@/lib/utils'

import { useAssetOperation, type AssetOperationController, type AssetOpStep } from './useAssetOperation'

const STATUS: Partial<Record<AssetOpStep, string>> = {
  preparing: 'Preparing the transaction…',
  submitting: 'Submitting to Stellar…',
  confirming: 'Waiting for the network to confirm…',
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-4 px-3 py-2">
      <dt className="shrink-0 text-[0.8125rem] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-sm">{children}</dd>
    </div>
  )
}

/** Review, sign and confirm one asset operation (a trustline or an asset contract deployment). */
export function AssetOperationDialog({
  controller,
  open,
  onOpenChange,
  title,
  description,
}: {
  controller: AssetOperationController
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
}) {
  const { step, prepared, operation, error } = controller
  const wallet = walletProviderName()
  const locked = step === 'signing' || step === 'submitting'
  const status = step === 'signing' ? `Waiting for your signature in ${wallet}…` : STATUS[step]

  const handleOpenChange = (next: boolean) => {
    if (!next && locked) return
    if (!next && step !== 'confirming') controller.reset()
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="gap-5 sm:max-w-lg" showCloseButton={!locked}>
        <DialogHeader className="gap-1.5 pr-8">
          <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <p aria-live="polite" className={cn('text-[0.8125rem] text-muted-foreground', !status && 'sr-only')}>
          {status}
        </p>

        {prepared && step !== 'confirmed' && <Summary prepared={prepared} />}

        {step === 'failed' && error && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertTitle>Not completed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {step === 'confirmed' && (
          <Alert variant="success">
            <CheckCircle2 />
            <AlertTitle>Confirmed on Stellar</AlertTitle>
          </Alert>
        )}

        {operation?.explorer_url && (step === 'confirmed' || step === 'confirming' || step === 'failed') && (
          <ExplorerLink operation={operation} />
        )}

        <DialogFooter>
          {step === 'review' && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={() => void controller.confirm()}>
                <Wallet aria-hidden /> Sign in {wallet}
              </Button>
            </>
          )}
          {step === 'failed' && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Close
              </Button>
              <Button onClick={() => void controller.start()}>
                <RotateCw aria-hidden /> Start again
              </Button>
            </>
          )}
          {step === 'confirming' && (
            <Button variant="outline" onClick={() => handleOpenChange(false)}>
              Close and keep tracking
            </Button>
          )}
          {step === 'confirmed' && <Button onClick={() => handleOpenChange(false)}>Done</Button>}
          {(step === 'preparing' || locked) && (
            <Button disabled>
              <LoaderCircle className="animate-spin" aria-hidden /> Working…
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Summary({ prepared }: { prepared: PreparedAssetOperation }) {
  const op = prepared.operation
  return (
    <dl className="divide-y overflow-hidden rounded-lg border">
      <Row label="Action">
        <span className="font-medium">{prepared.description}</span>
      </Row>
      <Row label="Wallet">
        <MonoValue
          value={op.source_address}
          label="wallet address"
          lead={4}
          tail={4}
          className="justify-end"
        />
      </Row>
      {op.asset.issuer && (
        <Row label="Issuer">
          <MonoValue
            value={op.asset.issuer}
            label={`${op.asset.code} issuer`}
            lead={4}
            tail={4}
            className="justify-end"
          />
        </Row>
      )}
      <Row label="Network">{networkDisplayName(prepared.network)}</Row>
      <Row label="Estimated fee">
        <span className="tabular-nums">{formatStroops(prepared.fee_estimate_stroops)}</span>
      </Row>
      <Row label="Expires">
        <span className="tabular-nums">{formatDateTime(prepared.expires_at)}</span>
      </Row>
    </dl>
  )
}

function ExplorerLink({ operation }: { operation: AssetOperation }) {
  if (!operation.explorer_url || !/^https:\/\//i.test(operation.explorer_url)) return null
  return (
    <a
      href={operation.explorer_url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="inline-flex min-h-9 items-center gap-1.5 text-sm font-medium text-primary-emphasis hover:underline"
    >
      View on explorer <ExternalLink className="size-3.5" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  )
}

/** A button that runs one asset operation in its dialog. */
export function AssetOperationButton({
  label,
  title,
  description,
  prepare,
  onConfirmed,
  confirmedToast,
  ...button
}: {
  label: string
  title: string
  description?: string
  prepare: () => Promise<PreparedAssetOperation>
  onConfirmed?: (op: AssetOperation) => void
  confirmedToast?: string
} & Omit<ComponentProps<typeof Button>, 'onClick' | 'children' | 'title'>) {
  const [open, setOpen] = useState(false)
  const controller = useAssetOperation({
    prepare,
    onConfirmed: (op) => {
      toast.success(confirmedToast ?? `${title}: confirmed on Stellar`)
      onConfirmed?.(op)
    },
  })
  return (
    <>
      <Button
        {...button}
        disabled={button.disabled || controller.busy}
        onClick={() => {
          setOpen(true)
          if (['idle', 'failed', 'confirmed'].includes(controller.step)) void controller.start()
        }}
      >
        {controller.step === 'confirming' ? 'Confirming…' : label}
      </Button>
      <AssetOperationDialog
        controller={controller}
        open={open}
        onOpenChange={setOpen}
        title={title}
        description={description}
      />
    </>
  )
}
