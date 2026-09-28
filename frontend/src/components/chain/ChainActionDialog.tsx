import { CheckCircle2, CircleAlert, LoaderCircle, RotateCw, Wallet } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
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
import type { TxType } from '@/lib/api/types'
import { burstCoins } from '@/lib/coin-burst'
import { formatDateTime } from '@/lib/format'
import { formatAmount, formatStroops } from '@/lib/money'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'
import { FREIGHTER_INSTALL_URL, walletProviderName } from '@/lib/stellar/wallet'
import type { ChainActionController, ChainStep } from '@/lib/stellar/useChainAction'
import { cn } from '@/lib/utils'

import { TransactionExplorerCard } from './TransactionExplorer'

type StepDef = { key: 'review' | 'sign' | 'submit' | 'confirm'; label: string }

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

function StepProgress({ step, failedAt }: { step: ChainStep; failedAt: number }) {
  const steps: StepDef[] = [
    { key: 'review', label: 'Review' },
    { key: 'sign', label: 'Sign' },
    { key: 'submit', label: 'Submit' },
    { key: 'confirm', label: 'Confirm' },
  ]
  const current = step === 'failed' ? failedAt : stepIndex(step)
  return (
    <ol className="grid grid-cols-4 gap-2" aria-label="Transaction progress">
      {steps.map((s, i) => {
        const done = current > i
        const active = current === i
        const failed = step === 'failed' && i === failedAt
        return (
          <li key={s.key} className="space-y-1.5" aria-current={active ? 'step' : undefined}>
            <div
              className={cn(
                'h-1 rounded-full bg-muted transition-colors',
                done && 'bg-primary',
                active && !failed && 'bg-primary/60',
                failed && 'bg-destructive',
              )}
            />
            <div
              className={cn(
                'text-xs',
                done || active ? 'text-foreground' : 'text-muted-foreground',
                failed && 'text-destructive',
              )}
            >
              {s.label}
              <span className="sr-only">{done ? ' (done)' : active ? ' (in progress)' : ''}</span>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <dt className="shrink-0 text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-sm">{children}</dd>
    </div>
  )
}

const STATUS_TEXT: Partial<Record<ChainStep, string>> = {
  preparing: 'Preparing the transaction with the escrow contract…',
  signing: 'Waiting for your signature in Freighter…',
  submitting: 'Submitting to the network…',
  confirming: 'Waiting for network confirmation. This usually takes a few seconds.',
}

/** Confirmed transactions that moved money get a coin burst: green when it reached a contributor. */
const MONEY_MOVES: Partial<Record<TxType, 'fund' | 'release'>> = {
  ESCROW_CREATE: 'fund',
  ESCROW_FUND: 'fund',
  PAYOUT: 'release',
  REFUND: 'fund',
}

/**
 * Review / sign / confirm dialog shared by every on-chain action.
 * Deliberately calm while you review and sign; the only flourish is a coin burst once the network has confirmed a
 * transaction that moved funds.
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

  const handleOpenChange = (next: boolean) => {
    if (!next && locked) return
    if (!next && step !== 'confirming') controller.reset()
    onOpenChange(next)
  }

  const summary = prepared?.summary
  const contractHref = contractExplorerUrl(config, summary?.contract_id)

  const confirmedAlert = useRef<HTMLDivElement>(null)
  const celebrated = useRef<string | null>(null)
  useEffect(() => {
    if (step !== 'confirmed' || !transaction || celebrated.current === transaction.id) return
    const tone = MONEY_MOVES[transaction.transaction_type]
    celebrated.current = transaction.id
    if (tone && confirmedAlert.current) void burstCoins(confirmedAlert.current, { tone })
  }, [step, transaction])

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg" showCloseButton={!locked}>
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <StepProgress step={step} failedAt={failedAt} />

        <div aria-live="polite" className="min-h-5 text-sm text-muted-foreground">
          {STATUS_TEXT[step] && (
            <span className="inline-flex items-center gap-2">
              <LoaderCircle className="size-4 animate-spin" aria-hidden /> {STATUS_TEXT[step]}
            </span>
          )}
        </div>

        {children && step !== 'confirmed' && <div className="text-sm">{children}</div>}

        {summary && step !== 'confirmed' && (
          <dl className="divide-y rounded-lg border px-3">
            <Row label="Action">
              <span className="font-medium">{summary.description}</span>
            </Row>
            <Row label="Amount">
              {summary.amount ? (
                <span className="text-base font-semibold tabular-nums">
                  {formatAmount(summary.amount)} {summary.asset?.code ?? 'XLM'}
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
              {error.detail && error.detail !== error.message && (
                <p className="mt-1 font-mono text-xs break-all opacity-80">{error.detail}</p>
              )}
              {error.kind === 'wallet_required' && (
                <Link
                  to="/app/profile"
                  className="mt-2 inline-block font-medium underline"
                  onClick={() => handleOpenChange(false)}
                >
                  Open your profile to connect and verify a wallet
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
          <Alert variant="success" ref={confirmedAlert}>
            <CheckCircle2 />
            <AlertTitle>Confirmed on Stellar</AlertTitle>
            <AlertDescription>
              The network confirmed this transaction. You can verify it independently on the explorer.
            </AlertDescription>
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
                <Wallet /> Sign in {walletProviderName()}
              </Button>
            </>
          )}
          {step === 'failed' && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Close
              </Button>
              <Button onClick={() => controller.start()}>
                <RotateCw /> Start again
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
              <LoaderCircle className="animate-spin" /> Working…
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
