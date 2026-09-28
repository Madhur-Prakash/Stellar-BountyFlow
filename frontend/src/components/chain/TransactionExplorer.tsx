import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { MonoValue } from '@/components/common/MonoValue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { BlockchainTransaction, PublicConfig } from '@/lib/api/types'
import { formatDateTime, formatRelative, TX_TYPE_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import {
  accountExplorerUrl,
  networkDisplayName,
  NOT_SUBMITTED,
  transactionExplorerHref,
} from '@/lib/stellar/explorer'
import { cn } from '@/lib/utils'

import { TxStatusBadge } from './TxStatusBadge'

function addressHref(config: PublicConfig | undefined, address: string | null) {
  return accountExplorerUrl(config, address)
}

function Amount({ tx }: { tx: BlockchainTransaction }) {
  if (!tx.amount) return <span className="text-muted-foreground">—</span>
  return (
    <span className="font-medium whitespace-nowrap tabular-nums">
      {formatAmount(tx.amount)} <span className="text-muted-foreground">{tx.asset?.code ?? 'XLM'}</span>
    </span>
  )
}

function ExplorerLink({ tx, config }: { tx: BlockchainTransaction; config: PublicConfig | undefined }) {
  const href = transactionExplorerHref(tx, config)
  if (!href) {
    return (
      <span className="text-xs text-muted-foreground">
        {NOT_SUBMITTED.has(tx.status) ? 'Never submitted to the network' : 'Not yet on-chain'}
      </span>
    )
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary-emphasis hover:underline"
    >
      View on explorer <ExternalLink className="size-3.5" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  )
}

function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0 space-y-1', className)}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  )
}

/** Full detail card for one blockchain transaction. */
export function TransactionExplorerCard({
  tx,
  className,
  title,
}: {
  tx: BlockchainTransaction
  className?: string
  title?: string
}) {
  const { data: config } = usePublicConfig()
  return (
    <Card className={cn('gap-4', className)}>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-base">{title ?? TX_TYPE_LABELS[tx.transaction_type]}</CardTitle>
        <div className="flex flex-wrap items-center gap-1.5">
          <TxStatusBadge status={tx.status} />
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
          <Field label="Network">{networkDisplayName(tx.network)}</Field>
          <Field label="Amount">
            <Amount tx={tx} />
          </Field>
          <Field label="Transaction hash" className="sm:col-span-2">
            {tx.transaction_hash ? (
              <MonoValue value={tx.transaction_hash} label="transaction hash" lead={10} tail={10} />
            ) : (
              <span className="text-muted-foreground">Assigned after submission</span>
            )}
          </Field>
          <Field label="Source">
            <MonoValue
              value={tx.source_address}
              label="source address"
              href={addressHref(config, tx.source_address)}
            />
          </Field>
          <Field label="Destination">
            <MonoValue
              value={tx.destination_address}
              label="destination address"
              href={addressHref(config, tx.destination_address)}
            />
          </Field>
          {tx.bounty_id && (
            <Field label="Bounty" className="sm:col-span-2">
              <Link
                to={`/bounties/${tx.bounty_id}`}
                className="inline-flex items-center gap-1 font-medium hover:underline"
              >
                {tx.bounty_title ?? 'View bounty'}
              </Link>
            </Field>
          )}
          <Field label="Submitted">
            <span className="tabular-nums">{formatDateTime(tx.submitted_at)}</span>
          </Field>
          <Field label="Confirmed">
            <span className="tabular-nums">{formatDateTime(tx.confirmed_at)}</span>
          </Field>
          {tx.ledger_sequence !== null && (
            <Field label="Ledger">
              <span className="font-mono tabular-nums">{tx.ledger_sequence}</span>
            </Field>
          )}
          {tx.failure_reason && (
            <Field label="Failure reason" className="sm:col-span-2">
              <span className="text-destructive">{tx.failure_reason}</span>
            </Field>
          )}
        </dl>
        <div className="mt-4 border-t pt-3">
          <ExplorerLink tx={tx} config={config} />
        </div>
      </CardContent>
    </Card>
  )
}

/** Responsive list of transactions: table from lg up, cards below (two per row on tablets). */
export function TransactionTable({
  transactions,
  showBounty = true,
  caption,
}: {
  transactions: BlockchainTransaction[]
  showBounty?: boolean
  caption?: string
}) {
  const { data: config } = usePublicConfig()
  return (
    <>
      <div className="hidden rounded-xl border lg:block">
        <Table>
          {caption && <caption className="sr-only">{caption}</caption>}
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead>Hash</TableHead>
              {showBounty && <TableHead>Bounty</TableHead>}
              <TableHead>Time</TableHead>
              <TableHead>Explorer</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {transactions.map((tx) => (
              <TableRow key={tx.id}>
                <TableCell className="font-medium whitespace-nowrap">
                  {TX_TYPE_LABELS[tx.transaction_type]}
                  <div className="text-xs font-normal text-muted-foreground">
                    {networkDisplayName(tx.network)}
                  </div>
                </TableCell>
                <TableCell>
                  <TxStatusBadge status={tx.status} />
                </TableCell>
                <TableCell className="text-right">
                  <Amount tx={tx} />
                </TableCell>
                <TableCell>
                  {tx.transaction_hash ? (
                    <MonoValue value={tx.transaction_hash} label="transaction hash" />
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                {showBounty && (
                  <TableCell className="max-w-48">
                    {tx.bounty_id ? (
                      <Link to={`/bounties/${tx.bounty_id}`} className="block truncate hover:underline">
                        {tx.bounty_title ?? 'Bounty'}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                )}
                <TableCell className="whitespace-nowrap text-muted-foreground tabular-nums">
                  <time
                    dateTime={tx.confirmed_at ?? tx.submitted_at ?? tx.created_at}
                    title={formatDateTime(tx.confirmed_at ?? tx.submitted_at ?? tx.created_at)}
                  >
                    {formatRelative(tx.confirmed_at ?? tx.submitted_at ?? tx.created_at)}
                  </time>
                </TableCell>
                <TableCell>
                  <ExplorerLink tx={tx} config={config} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="grid gap-3 sm:grid-cols-2 lg:hidden" aria-label={caption ?? 'Transactions'}>
        {transactions.map((tx) => (
          <li key={tx.id} className="rounded-xl border bg-card p-4 shadow-soft">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-medium">{TX_TYPE_LABELS[tx.transaction_type]}</div>
                <div className="text-xs text-muted-foreground">
                  {networkDisplayName(tx.network)} ·{' '}
                  {formatRelative(tx.confirmed_at ?? tx.submitted_at ?? tx.created_at)}
                </div>
              </div>
              <TxStatusBadge status={tx.status} />
            </div>
            <div className="mt-3 flex items-center justify-between gap-2">
              <Amount tx={tx} />
              {tx.transaction_hash && (
                <MonoValue value={tx.transaction_hash} label="transaction hash" lead={4} tail={4} />
              )}
            </div>
            {showBounty && tx.bounty_id && (
              <Link to={`/bounties/${tx.bounty_id}`} className="mt-2 block truncate text-sm hover:underline">
                {tx.bounty_title ?? 'Bounty'}
              </Link>
            )}
            <div className="mt-2">
              <ExplorerLink tx={tx} config={config} />
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}
