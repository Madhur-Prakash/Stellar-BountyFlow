import { ArrowLeftRight } from 'lucide-react'
import { useState } from 'react'

import { TransactionTable } from '@/components/chain/TransactionExplorer'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { useMyTransactions } from '@/lib/api/queries/chain'

export default function TransactionsPage() {
  const [page, setPage] = useState(1)
  const query = useMyTransactions({ page, page_size: 20 })
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Transactions"
        description="Every on-chain action you’ve prepared or signed. Confirmed transactions link to the Stellar explorer."
      />
      <QueryView
        query={query}
        skeleton="app-transactions"
        isEmpty={(d) => d.items.length === 0}
        empty={{
          icon: ArrowLeftRight,
          title: 'No transactions yet',
          description: 'Funding escrow, assignments, payouts, and wallet verifications will appear here.',
        }}
      >
        {(data) => (
          <>
            <TransactionTable transactions={data.items} caption="My transactions" />
            <PaginationBar
              page={data.page}
              pages={data.pages}
              total={data.total}
              pageSize={data.page_size}
              onPageChange={setPage}
              itemLabel="transactions"
            />
          </>
        )}
      </QueryView>
    </div>
  )
}
