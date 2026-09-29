import { CircleDollarSign } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { PaymentStatusBadge } from '@/components/bounty/WorkStatusBadges'
import { MonoValue } from '@/components/common/MonoValue'
import { UserAvatar } from '@/components/common/UserAvatar'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Card, CardFooter } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMyPayments } from '@/lib/api/queries/chain'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { PaymentRecord, PublicConfig } from '@/lib/api/types'
import { formatDate } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { transactionExplorerHref } from '@/lib/stellar/explorer'

import { CardQuery, CardToolbar, Money, ResponsiveTable } from './workspace-ui'

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

function PaymentHash({ payment, config }: { payment: PaymentRecord; config: PublicConfig | undefined }) {
  if (!payment.transaction?.transaction_hash) return <span className="text-muted-foreground">—</span>
  return (
    <MonoValue
      value={payment.transaction.transaction_hash}
      label="transaction hash"
      href={transactionExplorerHref(payment.transaction, config)}
      lead={4}
      tail={4}
    />
  )
}

const settledOn = (p: PaymentRecord) => formatDate(p.settled_at ?? p.created_at)

export default function PaymentsPage() {
  const [direction, setDirection] = useState<'received' | 'sent'>('received')
  const [page, setPage] = useState(1)
  const query = useMyPayments({ direction, page, page_size: 20 })
  const { data: config } = usePublicConfig()

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Workspace', to: '/app' }, { label: 'Payments' }]}
        title="Payments"
        description="Rewards you’ve received and payouts you’ve sent from escrow."
      />
      <Tabs
        value={direction}
        onValueChange={(v) => {
          setDirection(v as 'received' | 'sent')
          setPage(1)
        }}
      >
        <Card className="gap-0 py-0">
          <CardToolbar>
            <TabsList className="h-9">
              <TabsTrigger value="received" className="px-3">
                Received
              </TabsTrigger>
              <TabsTrigger value="sent" className="px-3">
                Sent
              </TabsTrigger>
            </TabsList>
          </CardToolbar>

          <TabsContent value={direction}>
            <CardQuery
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
                  <ResponsiveTable
                    caption={`Payments ${direction}`}
                    rows={data.items}
                    getKey={(p) => p.id}
                    stackBelow="lg"
                    columns={[
                      {
                        key: 'bounty',
                        header: 'Bounty',
                        className: 'min-w-56 whitespace-normal',
                        cell: (p) => <PaymentBountyLink payment={p} />,
                      },
                      {
                        key: 'contributor',
                        header: 'Contributor',
                        cell: (p) => (
                          <span className="inline-flex items-center gap-2">
                            <UserAvatar user={p.contributor} className="size-6" />{' '}
                            {p.contributor.display_name}
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
                        cell: (p) => <PaymentHash payment={p} config={config} />,
                      },
                      {
                        key: 'date',
                        header: 'Settled',
                        cell: (p) => (
                          <span className="text-muted-foreground tabular-nums">{settledOn(p)}</span>
                        ),
                      },
                      {
                        key: 'amount',
                        header: 'Amount',
                        className: 'text-right',
                        cell: (p) => <Money amount={formatAmount(p.amount)} asset={p.asset.code} />,
                      },
                    ]}
                    renderMobile={(p) => (
                      <div className="space-y-2">
                        <div className="flex items-start justify-between gap-3">
                          <PaymentBountyLink payment={p} />
                          <Money amount={formatAmount(p.amount)} asset={p.asset.code} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted-foreground">
                          <PaymentStatusBadge status={p.payment_status} />
                          <span className="inline-flex items-center gap-1.5">
                            <UserAvatar user={p.contributor} className="size-5" />{' '}
                            {p.contributor.display_name}
                          </span>
                          <span className="tabular-nums">{settledOn(p)}</span>
                        </div>
                        {p.transaction?.transaction_hash && <PaymentHash payment={p} config={config} />}
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
                      itemLabel="payments"
                      className="w-full pt-0"
                    />
                  </CardFooter>
                </>
              )}
            </CardQuery>
          </TabsContent>
        </Card>
      </Tabs>
    </div>
  )
}
