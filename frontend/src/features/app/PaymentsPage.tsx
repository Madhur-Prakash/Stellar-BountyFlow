import { CircleDollarSign } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { PaymentStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { MonoValue } from '@/components/common/MonoValue'
import { UserAvatar } from '@/components/common/UserAvatar'
import { DataTable } from '@/components/layout/DataTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMyPayments } from '@/lib/api/queries/chain'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { PaymentRecord } from '@/lib/api/types'
import { formatDate } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { transactionExplorerHref } from '@/lib/stellar/explorer'

/** Links to the paid bounty; the API sends its title/slug with each payment. */
function PaymentBountyLink({ payment }: { payment: PaymentRecord }) {
  const title = payment.bounty_title ?? payment.transaction?.bounty_title ?? null
  return (
    <Link
      to={`/bounties/${payment.bounty_slug || payment.transaction?.bounty_slug || payment.bounty_id}`}
      className="line-clamp-2 font-medium hover:underline"
    >
      {title ?? 'View bounty'}
    </Link>
  )
}

export default function PaymentsPage() {
  const [direction, setDirection] = useState<'received' | 'sent'>('received')
  const [page, setPage] = useState(1)
  const query = useMyPayments({ direction, page, page_size: 20 })
  const { data: config } = usePublicConfig()

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Payments"
        description="Rewards you’ve received and payouts you’ve sent from escrow."
      />
      <Tabs
        value={direction}
        onValueChange={(v) => {
          setDirection(v as 'received' | 'sent')
          setPage(1)
        }}
        className="mb-4"
      >
        <TabsList>
          <TabsTrigger value="received">Received</TabsTrigger>
          <TabsTrigger value="sent">Sent</TabsTrigger>
        </TabsList>

        <TabsContent value={direction}>
          <QueryView
            query={query}
            skeleton="app-payments"
            isEmpty={(d) => d.items.length === 0}
            empty={{
              icon: CircleDollarSign,
              title: direction === 'received' ? 'No payments received yet' : 'No payouts sent yet',
              description:
                direction === 'received'
                  ? 'Payouts appear here after a requester approves your submission.'
                  : 'Payouts you release from escrow will be listed here.',
            }}
          >
            {(data) => (
              <>
                <DataTable
                  caption={`Payments ${direction}`}
                  rows={data.items}
                  getKey={(p) => p.id}
                  mobileTitle={(p) => <PaymentBountyLink payment={p} />}
                  columns={[
                    {
                      key: 'bounty',
                      header: 'Bounty',
                      mobileHidden: true,
                      cell: (p) => <PaymentBountyLink payment={p} />,
                    },
                    {
                      key: 'contributor',
                      header: 'Contributor',
                      cell: (p) => (
                        <span className="inline-flex items-center gap-2">
                          <UserAvatar user={p.contributor} className="size-6" /> {p.contributor.display_name}
                        </span>
                      ),
                    },
                    {
                      key: 'amount',
                      header: 'Amount',
                      className: 'text-right',
                      cell: (p) => (
                        <span className="font-medium tabular-nums">
                          {formatAmount(p.amount)}{' '}
                          <span className="text-muted-foreground">{p.asset.code}</span>
                        </span>
                      ),
                    },
                    {
                      key: 'status',
                      header: 'Status',
                      cell: (p) => <PaymentStatusBadge status={p.payment_status} />,
                    },
                    {
                      key: 'tx',
                      header: 'Transaction',
                      cell: (p) =>
                        p.transaction?.transaction_hash ? (
                          <MonoValue
                            value={p.transaction.transaction_hash}
                            label="transaction hash"
                            href={transactionExplorerHref(p.transaction, config)}
                            lead={4}
                            tail={4}
                          />
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        ),
                    },
                    {
                      key: 'date',
                      header: 'Settled',
                      cell: (p) => (
                        <span className="text-muted-foreground">
                          {formatDate(p.settled_at ?? p.created_at)}
                        </span>
                      ),
                    },
                  ]}
                />
                <PaginationBar
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  pageSize={data.page_size}
                  onPageChange={setPage}
                  itemLabel="payments"
                />
              </>
            )}
          </QueryView>
        </TabsContent>
      </Tabs>
    </div>
  )
}
