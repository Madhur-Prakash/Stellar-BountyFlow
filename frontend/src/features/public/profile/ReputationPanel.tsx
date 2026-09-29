import { ShieldCheck } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { MonoValue } from '@/components/common/MonoValue'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { RowsSkeleton } from '@/features/app/workspace-ui'
import { AttestationRows } from '@/features/reputation/AttestationRows'
import { useReputationSummary, useUserAttestations } from '@/lib/api/queries/reputation'
import type { ReputationSummary } from '@/lib/api/types'
import { formatDate, formatNumber } from '@/lib/format'
import { formatAssetAmounts } from '@/lib/money'

/** The "Completed on-chain" tab: completions recorded in the attestation registry. */
export function CompletedOnChain({ username }: { username: string }) {
  const [page, setPage] = useState(1)
  const { data, isPending, isError, error, refetch } = useUserAttestations(username, { page, page_size: 10 })
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />
  if (!isPending && data.items.length === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="No completions recorded on-chain yet"
        description="A completion is recorded here once its payout is verified and attested on Stellar."
      />
    )
  }
  return (
    <Bones
      name="public-profile-attestations"
      loading={isPending}
      fallback={<RowsSkeleton rows={3} className="rounded-xl border bg-card shadow-soft" />}
    >
      {data && (
        <>
          <div className="overflow-hidden rounded-xl border bg-card shadow-soft">
            <AttestationRows items={data.items} label="Completions recorded on-chain" />
          </div>
          <PaginationBar
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={data.page_size}
            onPageChange={setPage}
            itemLabel="completions"
          />
        </>
      )}
    </Bones>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 first:pt-0 last:pb-0">
      <dt className="text-[0.8125rem] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-sm font-medium tabular-nums">{children}</dd>
    </div>
  )
}

function SummaryBody({ summary }: { summary: ReputationSummary }) {
  if (!summary.enabled) {
    return (
      <p className="text-sm text-muted-foreground">On-chain attestations are not set up on this server.</p>
    )
  }
  return (
    <div className="space-y-4">
      <dl className="divide-y">
        <Row label="Completed on-chain">{formatNumber(summary.attested_completions)}</Row>
        <Row label="Earned">{formatAssetAmounts(summary.earned, { maxDecimals: 2 })}</Row>
        {summary.first_completed_at && (
          <Row label="First completion">{formatDate(summary.first_completed_at)}</Row>
        )}
        {summary.last_completed_at && (
          <Row label="Latest completion">{formatDate(summary.last_completed_at)}</Row>
        )}
        {summary.revoked > 0 && <Row label="Revoked">{formatNumber(summary.revoked)}</Row>}
      </dl>
      {summary.contract_id && (
        <div className="space-y-1 border-t pt-3">
          <p className="text-xs text-muted-foreground">Attestation registry</p>
          <MonoValue
            value={summary.contract_id}
            label="attestation registry contract"
            href={summary.contract_explorer_url}
            className="-my-1"
          />
        </div>
      )}
    </div>
  )
}

/** Aside card: the contributor's reputation from attested completions only. */
export function ReputationCard({ username }: { username: string }) {
  const { data, isPending, isError, error, refetch } = useReputationSummary(username)
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="font-mono text-[0.8125rem] font-normal tracking-[0.01em] text-muted-foreground">
          <h2>On-chain record</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isError ? (
          <ErrorState error={error} onRetry={() => refetch()} />
        ) : (
          <Bones
            name="public-profile-reputation"
            loading={isPending}
            fallback={
              <div role="status" aria-label="Loading" className="space-y-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-4 w-3/5" />
              </div>
            }
          >
            {data && <SummaryBody summary={data} />}
          </Bones>
        )}
      </CardContent>
    </Card>
  )
}
