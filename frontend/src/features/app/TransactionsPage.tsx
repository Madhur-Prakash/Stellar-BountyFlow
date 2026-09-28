import { ArrowLeftRight, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { TxStatusBadge } from '@/components/chain/TxStatusBadge'
import { MonoValue } from '@/components/common/MonoValue'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Card, CardFooter } from '@/components/ui/card'
import { useMyTransactions } from '@/lib/api/queries/chain'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { BlockchainTransaction, PublicConfig } from '@/lib/api/types'
import { formatDateTime, formatRelative, TX_TYPE_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { networkDisplayName, NOT_SUBMITTED, transactionExplorerHref } from '@/lib/stellar/explorer'

import { CardQuery, Money, ResponsiveTable } from './workspace-ui'

const when = (tx: BlockchainTransaction) => tx.confirmed_at ?? tx.submitted_at ?? tx.created_at

function Amount({ tx }: { tx: BlockchainTransaction }) {
  if (!tx.amount) return <span className="text-muted-foreground">—</span>
  return <Money amount={formatAmount(tx.amount)} asset={tx.asset?.code ?? 'XLM'} />
}

function Time({ tx }: { tx: BlockchainTransaction }) {
  return (
    <time dateTime={when(tx)} title={formatDateTime(when(tx))} className="tabular-nums">
      {formatRelative(when(tx))}
    </time>
  )
}

function BountyLink({ tx }: { tx: BlockchainTransaction }) {
  if (!tx.bounty_id) return <span className="text-muted-foreground">—</span>
  return (
    <Link to={`/bounties/${tx.bounty_id}`} className="line-clamp-2 hover:underline">
      {tx.bounty_title ?? 'Bounty'}
    </Link>
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

export default function TransactionsPage() {
  const [page, setPage] = useState(1)
  const query = useMyTransactions({ page, page_size: 20 })
  const { data: config } = usePublicConfig()
  return (
    <div>
      <PageHeader title="Transactions" description="On-chain actions you’ve prepared or signed." />
      <Card className="gap-0 py-0">
        <CardQuery
          query={query}
          skeleton="app-transactions"
          isEmpty={(d) => d.items.length === 0}
          empty={{
            icon: ArrowLeftRight,
            title: 'No transactions yet',
            description: 'Funding escrow, assignments, payouts and wallet verifications will appear here.',
          }}
        >
          {(data) => (
            <>
              <ResponsiveTable
                caption="My transactions"
                rows={data.items}
                getKey={(tx) => tx.id}
                stackBelow="lg"
                columns={[
                  {
                    key: 'type',
                    header: 'Type',
                    cell: (tx) => (
                      <>
                        <div className="font-medium">{TX_TYPE_LABELS[tx.transaction_type]}</div>
                        <div className="text-xs text-muted-foreground">{networkDisplayName(tx.network)}</div>
                      </>
                    ),
                  },
                  { key: 'status', header: 'Status', cell: (tx) => <TxStatusBadge status={tx.status} /> },
                  {
                    key: 'bounty',
                    header: 'Bounty',
                    className: 'min-w-48 max-w-72 whitespace-normal',
                    cell: (tx) => <BountyLink tx={tx} />,
                  },
                  {
                    key: 'hash',
                    header: 'Hash',
                    cell: (tx) =>
                      tx.transaction_hash ? (
                        <MonoValue value={tx.transaction_hash} label="transaction hash" lead={4} tail={4} />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      ),
                  },
                  {
                    key: 'time',
                    header: 'Time',
                    className: 'text-muted-foreground',
                    cell: (tx) => <Time tx={tx} />,
                  },
                  {
                    key: 'explorer',
                    header: 'Explorer',
                    cell: (tx) => <ExplorerLink tx={tx} config={config} />,
                  },
                  {
                    key: 'amount',
                    header: 'Amount',
                    className: 'text-right',
                    cell: (tx) => <Amount tx={tx} />,
                  },
                ]}
                renderMobile={(tx) => (
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-medium">{TX_TYPE_LABELS[tx.transaction_type]}</div>
                        <div className="text-xs text-muted-foreground">
                          {networkDisplayName(tx.network)}, <Time tx={tx} />
                        </div>
                      </div>
                      <Amount tx={tx} />
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <TxStatusBadge status={tx.status} />
                      {tx.transaction_hash && (
                        <MonoValue value={tx.transaction_hash} label="transaction hash" lead={4} tail={4} />
                      )}
                    </div>
                    {tx.bounty_id && (
                      <div className="text-sm">
                        <BountyLink tx={tx} />
                      </div>
                    )}
                    <ExplorerLink tx={tx} config={config} />
                  </div>
                )}
              />
              <CardFooter className="px-4 py-3 sm:px-5">
                <PaginationBar
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  pageSize={data.page_size}
                  onPageChange={setPage}
                  itemLabel="transactions"
                  className="w-full pt-0"
                />
              </CardFooter>
            </>
          )}
        </CardQuery>
      </Card>
    </div>
  )
}
