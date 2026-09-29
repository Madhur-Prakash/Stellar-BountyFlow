import { ArrowLeftRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { TxStatusBadge } from '@/components/chain/TxStatusBadge'
import { MonoValue } from '@/components/common/MonoValue'
import { PageHeader } from '@/components/layout/PageHeader'
import { useAdminTransactions } from '@/lib/api/queries/admin'
import { usePublicConfig } from '@/lib/api/queries/config'
import {
  TX_STATUSES,
  TX_TYPES,
  type BlockchainTransaction,
  type TxStatus,
  type TxType,
} from '@/lib/api/types'
import { formatDateTime, formatRelative, TX_STATUS_LABELS, TX_TYPE_LABELS } from '@/lib/format'
import { assetCode, formatAmount } from '@/lib/money'
import { networkDisplayName, NOT_SUBMITTED, transactionExplorerHref } from '@/lib/stellar/explorer'

import { AdminTable, FilterSelect, PagedResults, UserCell, type AdminColumn } from './admin-shared'
import { ADMIN_PAGE_SIZE, bountyPath, scrollToTop, useFilteredPage } from './admin-utils'

function txTime(tx: BlockchainTransaction) {
  return tx.confirmed_at ?? tx.submitted_at ?? tx.created_at
}

export default function AdminTransactionsPage() {
  const { data: config } = usePublicConfig()
  const [status, setStatus] = useState<TxStatus | undefined>(undefined)
  const [type, setType] = useState<TxType | undefined>(undefined)
  const [page, setPage] = useFilteredPage(`${status ?? ''}|${type ?? ''}`)
  const query = useAdminTransactions({ status, type, page, page_size: ADMIN_PAGE_SIZE })

  const columns: AdminColumn<BlockchainTransaction>[] = [
    {
      key: 'type',
      header: 'Type',
      mobile: 'title',
      cell: (tx) => (
        <div>
          <div className="leading-5 font-medium">{TX_TYPE_LABELS[tx.transaction_type]}</div>
          <div className="text-xs leading-4 text-muted-foreground">{networkDisplayName(tx.network)}</div>
        </div>
      ),
    },
    { key: 'status', header: 'Status', mobile: 'aside', cell: (tx) => <TxStatusBadge status={tx.status} /> },
    {
      key: 'amount',
      header: 'Amount',
      className: 'text-right',
      cell: (tx) =>
        tx.amount ? (
          <span className="whitespace-nowrap">
            <span className="amount">{formatAmount(tx.amount)}</span>{' '}
            <span className="text-xs text-muted-foreground">{assetCode(tx.asset)}</span>
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'account',
      header: 'Account',
      cell: (tx) =>
        tx.user ? (
          <UserCell user={tx.user} avatar={false} />
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'hash',
      header: 'Hash',
      cell: (tx) => {
        if (!tx.transaction_hash) {
          const why = NOT_SUBMITTED.has(tx.status) ? 'Never submitted to the network' : 'Not yet on-chain'
          return (
            <span className="text-muted-foreground" title={why}>
              <span aria-hidden>—</span>
              <span className="sr-only">{why}</span>
            </span>
          )
        }
        return (
          <MonoValue
            value={tx.transaction_hash}
            label="transaction hash"
            lead={4}
            tail={4}
            href={transactionExplorerHref(tx, config)}
          />
        )
      },
    },
    {
      key: 'bounty',
      header: 'Bounty',
      wide: true,
      mobileOrder: 99,
      cell: (tx) =>
        tx.bounty_id ? (
          <Link
            to={bountyPath({ id: tx.bounty_id, slug: tx.bounty_slug })}
            title={tx.bounty_title ?? undefined}
            className="block truncate hover:underline min-[1400px]:max-w-56 lg:max-w-36"
          >
            {tx.bounty_title ?? 'Bounty'}
          </Link>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'time',
      header: 'Time',
      cell: (tx) => (
        <time
          dateTime={txTime(tx)}
          title={formatDateTime(txTime(tx))}
          className="whitespace-nowrap text-muted-foreground tabular-nums"
        >
          {formatRelative(txTime(tx))}
        </time>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title="Transactions"
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Transactions' }]}
      />

      <PagedResults
        query={query}
        skeleton="admin-transactions"
        label="Transactions"
        itemLabel="transactions"
        errorTitle="Could not load transactions"
        empty={{ icon: ArrowLeftRight, title: 'No transactions yet' }}
        filtered={!!status || !!type}
        onClearFilters={() => {
          setStatus(undefined)
          setType(undefined)
        }}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <>
            <FilterSelect
              id="admin-tx-status"
              label="Filter by status"
              value={status}
              onChange={setStatus}
              options={TX_STATUSES}
              labels={TX_STATUS_LABELS}
              allLabel="All statuses"
            />
            <FilterSelect
              id="admin-tx-type"
              label="Filter by type"
              value={type}
              onChange={setType}
              options={TX_TYPES}
              labels={TX_TYPE_LABELS}
              allLabel="All types"
            />
          </>
        }
      >
        {(items) => (
          <AdminTable rows={items} columns={columns} getKey={(tx) => tx.id} caption="Platform transactions" />
        )}
      </PagedResults>
    </div>
  )
}
