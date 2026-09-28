import { ArrowLeftRight } from 'lucide-react'
import { useState } from 'react'

import { TransactionTable } from '@/components/chain/TransactionExplorer'
import { PageHeader } from '@/components/layout/PageHeader'
import { useAdminTransactions } from '@/lib/api/queries/admin'
import { TX_STATUSES, TX_TYPES, type TxStatus, type TxType } from '@/lib/api/types'
import { TX_STATUS_LABELS, TX_TYPE_LABELS } from '@/lib/format'

import { FilterBar, FilterSelect, PagedResults } from './admin-shared'
import { ADMIN_PAGE_SIZE, scrollToTop, useFilteredPage } from './admin-utils'

export default function AdminTransactionsPage() {
  const [status, setStatus] = useState<TxStatus | undefined>(undefined)
  const [type, setType] = useState<TxType | undefined>(undefined)
  const [page, setPage] = useFilteredPage(`${status ?? ''}|${type ?? ''}`)
  const query = useAdminTransactions({ status, type, page, page_size: ADMIN_PAGE_SIZE })

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Transactions"
        description="Every escrow, payout, refund, and dispute transaction across the platform, with links to verify each one on the explorer."
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Transactions' }]}
      />

      <FilterBar>
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
      </FilterBar>

      <PagedResults
        query={query}
        skeleton="admin-transactions"
        label="Transactions"
        itemLabel="transactions"
        errorTitle="Could not load transactions"
        empty={{
          icon: ArrowLeftRight,
          title: 'No transactions yet',
          description: 'Blockchain transactions appear here once users fund, pay out, or verify wallets.',
        }}
        filtered={!!status || !!type}
        onClearFilters={() => {
          setStatus(undefined)
          setType(undefined)
        }}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
      >
        {(items) => <TransactionTable transactions={items} showBounty caption="Platform transactions" />}
      </PagedResults>
    </div>
  )
}
