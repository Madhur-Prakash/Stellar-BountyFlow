import { ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { MetaList } from '@/components/bounty/MetaList'
import { MonoValue } from '@/components/common/MonoValue'
import { Badge } from '@/components/ui/badge'
import type { Attestation, AttestationStatus } from '@/lib/api/types'
import { formatDate } from '@/lib/format'
import { formatMoney } from '@/lib/money'
import { cn } from '@/lib/utils'

const STATUS: Record<
  AttestationStatus,
  { label: string; variant: 'success' | 'danger' | 'muted' | 'warning' }
> = {
  CONFIRMED: { label: 'Completed on-chain', variant: 'success' },
  REVOKING: { label: 'Revoking', variant: 'warning' },
  REVOKED: { label: 'Revoked', variant: 'danger' },
  PENDING: { label: 'Recording on-chain', variant: 'muted' },
  SUBMITTED: { label: 'Recording on-chain', variant: 'muted' },
  FAILED: { label: 'Not recorded', variant: 'warning' },
}

export function AttestationStatusBadge({ status }: { status: AttestationStatus }) {
  const s = STATUS[status]
  return (
    <Badge variant={s.variant}>
      {status === 'CONFIRMED' && <ShieldCheck aria-hidden />}
      {s.label}
    </Badge>
  )
}

export function AttestationAmount({
  attestation,
  className,
}: {
  attestation: Attestation
  className?: string
}) {
  return (
    <span className={cn('whitespace-nowrap', className)}>
      <span className="amount">{formatMoney(attestation.amount, attestation.asset)}</span>
    </span>
  )
}

/**
 * Attested completions as rows inside a card: the bounty, when it was completed, the amount and asset, the status,
 * and explorer links for the attestation and the payout. `actions` adds per-row controls (the owner's download).
 */
export function AttestationRows({
  items,
  label,
  actions,
}: {
  items: Attestation[]
  label: string
  actions?: (attestation: Attestation) => ReactNode
}) {
  return (
    <ul aria-label={label} className="divide-y">
      {items.map((a) => {
        const recorded =
          a.onchain_id !== null &&
          (a.status === 'CONFIRMED' || a.status === 'REVOKED' || a.status === 'REVOKING')
        return (
          <li
            key={a.id}
            className="flex flex-col gap-3 px-4 py-4 sm:px-5 lg:flex-row lg:items-start lg:justify-between"
          >
            <div className="min-w-0 space-y-1.5">
              <Link
                to={`/bounties/${a.bounty.slug || a.bounty.id}`}
                className="block truncate text-sm font-medium hover:underline"
              >
                {a.bounty.title}
              </Link>
              <MetaList>
                <span>Completed {formatDate(a.completed_at)}</span>
                {a.payments_count > 1 && <span>{a.payments_count} payments</span>}
                {recorded && (
                  <Link
                    to={`/attestations/${a.onchain_id}`}
                    className="inline-flex min-h-6 items-center text-primary-emphasis hover:underline"
                  >
                    Attestation #{a.onchain_id}
                  </Link>
                )}
                {a.status === 'REVOKED' && a.revocation_reason && <span>{a.revocation_reason}</span>}
              </MetaList>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {recorded && a.attestation_tx_hash && (
                  <span className="inline-flex items-center gap-1.5">
                    Attested
                    <MonoValue
                      value={a.attestation_tx_hash}
                      label="attestation transaction hash"
                      href={a.attestation_explorer_url}
                      lead={4}
                      tail={4}
                    />
                  </span>
                )}
                <span className="inline-flex items-center gap-1.5">
                  Paid
                  <MonoValue
                    value={a.payout_tx_hash}
                    label="payout transaction hash"
                    href={a.payout_explorer_url}
                    lead={4}
                    tail={4}
                  />
                </span>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-3 lg:flex-col lg:items-end">
              <AttestationAmount attestation={a} className="text-sm" />
              <AttestationStatusBadge status={a.status} />
              {actions?.(a)}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
