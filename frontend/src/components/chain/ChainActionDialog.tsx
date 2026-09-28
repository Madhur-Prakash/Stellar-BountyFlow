import { Check, CheckCircle2, CircleAlert, LoaderCircle, RotateCw, Wallet, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

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
import { usePublicConfig } from '@/lib/api/queries/config'
import { formatDateTime } from '@/lib/format'
import { formatAmount, formatStroops } from '@/lib/money'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'
import { FREIGHTER_INSTALL_URL, walletProviderName } from '@/lib/stellar/wallet'
import type { ChainActionController, ChainErrorKind, ChainStep } from '@/lib/stellar/useChainAction'
import { cn } from '@/lib/utils'

import { TransactionExplorerCard } from './TransactionExplorer'

const STEPS = [
  { key: 'review', label: 'Review' },
  { key: 'sign', label: 'Sign' },
  { key: 'submit', label: 'Submit' },
  { key: 'confirm', label: 'Confirm' },
] as const

function stepIndex(step: ChainStep): number {
  switch (step) {
    case 'idle':
    case 'preparing':
    case 'awaiting_review':
      return 0
    case 'signing':
      return 1
    case 'submitting':
      return 2
    case 'confirming':
      return 3
    case 'confirmed':
      return 4
    case 'failed':
      return -1
  }
}

const BUSY: ReadonlySet<ChainStep> = new Set(['preparing', 'signing', 'submitting', 'confirming'])

/** Failures whose message already says everything; the wallet's own wording would only repeat it. */
const PLAIN_ERRORS: ReadonlySet<ChainErrorKind> = new Set(['user_rejected', 'wallet_not_installed'])

/** Review → Sign → Submit → Confirm, as numbered steps joined by a line. */
function StepProgress({ step, failedAt }: { step: ChainStep; failedAt: number }) {
  const current = step === 'failed' ? failedAt : stepIndex(step)
  return (
    <ol className="flex items-center" aria-label="Transaction progress">
      {STEPS.map((s, i) => {
        const done = current > i
        const active = current === i
        const failed = step === 'failed' && i === failedAt
        const busy = active && BUSY.has(step)
        return (
          <li
            key={s.key}
            className={cn('flex items-center', i < STEPS.length - 1 && 'flex-1')}
            aria-current={active ? 'step' : undefined}
          >
            <span className="flex items-center gap-2">
              <span
                aria-hidden
                className={cn(
                  'flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium tabular-nums transition-colors',
                  done && 'border-primary bg-primary text-primary-foreground',
                  active && !failed && 'border-primary bg-primary/10 text-primary-emphasis',
                  failed && 'border-destructive/40 bg-destructive/10 text-destructive',
                  !done && !active && !failed && 'bg-card text-muted-foreground',
                )}
              >
                {done ? (
                  <Check className="size-3.5" />
                ) : failed ? (
                  <X className="size-3.5" />
                ) : busy ? (
                  <LoaderCircle className="size-3.5 animate-spin" />
                ) : (
                  i + 1
                )}
              </span>
              <span
                className={cn(
                  'text-[0.8125rem]',
                  done || active ? 'font-medium text-foreground' : 'text-muted-foreground',
                  failed && 'text-destructive',
                  // On phones only the current step is labelled; the others keep their label for screen readers.
                  !active && !failed && 'max-sm:sr-only',
                )}
              >
                {s.label}
                <span className="sr-only">
                  {done ? ' (done)' : failed ? ' (failed)' : active ? ' (in progress)' : ''}
                </span>
              </span>
            </span>
            {i < STEPS.length - 1 && (
              <span
                aria-hidden
                className={cn('mx-1.5 h-px min-w-2 flex-1 bg-border sm:mx-2', done && 'bg-primary')}
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-4 px-3 py-2">
      <dt className="shrink-0 text-[0.8125rem] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-sm">{children}</dd>
    </div>
  )
}

/**
 * Review / sign / confirm dialog shared by every on-chain action. It states what is being signed and on which
 * network, then follows the transaction until the network confirms it.
 */
export function ChainActionDialog({
  controller,
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  controller: ChainActionController
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  /** Action-specific context (e.g. who must sign) shown above the summary. */
  children?: ReactNode
}) {
  const { data: config } = usePublicConfig()
  const { step, prepared, transaction, error } = controller
  const locked = step === 'signing' || step === 'submitting'
  const failedAt = lastActiveIndex(controller)
  const wallet = walletProviderName()

  const statusText: Partial<Record<ChainStep, string>> = {
    preparing: 'Preparing the transaction…',
    signing: `Waiting for your signature in ${wallet}…`,
    submitting: 'Submitting to Stellar…',
    confirming: 'Waiting for the network to confirm…',
  }

  const handleOpenChange = (next: boolean) => {
    if (!next && locked) return
    if (!next && step !== 'confirming') controller.reset()
    onOpenChange(next)
  }

  const summary = prepared?.summary
  const contractHref = contractExplorerUrl(config, summary?.contract_id)

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="gap-5 sm:max-w-lg" showCloseButton={!locked}>
        <DialogHeader className="gap-1.5 pr-8">
          <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <div>
          <StepProgress step={step} failedAt={failedAt} />
          {/* Always mounted, so screen readers announce each status as it changes. */}
          <p
            aria-live="polite"
            className={cn('text-[0.8125rem] text-muted-foreground', statusText[step] && 'mt-3')}
          >
            {statusText[step]}
          </p>
        </div>

        {children && step !== 'confirmed' && <div className="text-sm">{children}</div>}

        {summary && step !== 'confirmed' && (
          <dl className="divide-y overflow-hidden rounded-lg border">
            <Row label="Action">
              <span className="font-medium">{summary.description}</span>
            </Row>
            <Row label="Amount">
              {summary.amount ? (
                <span className="amount text-[0.9375rem]">
                  {formatAmount(summary.amount)}{' '}
                  <span className="font-normal text-muted-foreground">{summary.asset?.code ?? 'XLM'}</span>
                </span>
              ) : (
                <span className="text-muted-foreground">No transfer</span>
              )}
            </Row>
            <Row label="Network">{networkDisplayName(prepared?.network ?? config?.network)}</Row>
            <Row label="Contract">
              {summary.contract_id ? (
                <MonoValue value={summary.contract_id} label="contract id" href={contractHref} />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </Row>
            <Row label="Function">
              <code className="font-mono text-[0.8125rem]">{summary.function_name}</code>
            </Row>
            <Row label="Estimated fee">
              <span className="tabular-nums">{formatStroops(summary.fee_estimate_stroops)}</span>
            </Row>
            {prepared && (
              <Row label="Expires">
                <span className="tabular-nums">{formatDateTime(prepared.expires_at)}</span>
              </Row>
            )}
          </dl>
        )}

        {step === 'failed' && error && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertTitle>Transaction not completed</AlertTitle>
            <AlertDescription>
              <p>{error.message}</p>
              {error.detail && error.detail !== error.message && !PLAIN_ERRORS.has(error.kind) && (
                <p className="mt-1 font-mono text-xs break-all opacity-80">{error.detail}</p>
              )}
              {error.kind === 'wallet_required' && (
                <Link
                  to="/app/profile"
                  className="mt-2 inline-block font-medium underline"
                  onClick={() => handleOpenChange(false)}
                >
                  Connect and verify a wallet in your profile
                </Link>
              )}
              {error.kind === 'wallet_not_installed' && (
                <a
                  href={FREIGHTER_INSTALL_URL}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="mt-2 inline-block font-medium underline"
                >
                  Install Freighter
                </a>
              )}
            </AlertDescription>
          </Alert>
        )}

        {step === 'confirmed' && (
          <Alert variant="success">
            <CheckCircle2 />
            <AlertTitle>Confirmed on Stellar</AlertTitle>
          </Alert>
        )}

        {transaction &&
          (step === 'confirmed' ||
            step === 'confirming' ||
            (step === 'failed' && transaction.status !== 'SIGNATURE_REQUIRED')) && (
            <TransactionExplorerCard tx={transaction} />
          )}

        <DialogFooter>
          {step === 'awaiting_review' && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={() => controller.confirm()}>
                <Wallet aria-hidden /> Sign in {wallet}
              </Button>
            </>
          )}
          {step === 'failed' && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Close
              </Button>
              <Button onClick={() => controller.start()}>
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

/** Which progress step the failure happened at (derived from what data exists). */
function lastActiveIndex(c: ChainActionController): number {
  if (c.step !== 'failed') return -1
  if (!c.prepared) return 0
  const status = c.transaction?.status
  if (status === 'SUBMITTED' || status === 'FAILED' || status === 'EXPIRED') return 3
  if (c.error?.kind === 'user_rejected' || c.error?.kind === 'network_mismatch') return 1
  return c.transaction && status !== 'SIGNATURE_REQUIRED' ? 2 : 1
}
