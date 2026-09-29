import { CircleAlert, CircleCheck, CircleX } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'

import { MonoValue } from '@/components/common/MonoValue'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { LoadingState } from '@/components/layout/LoadingState'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import NotFoundPage from '@/features/public/NotFoundPage'
import { isApiError } from '@/lib/api/client'
import { useAttestation } from '@/lib/api/queries/reputation'
import type { AttestationChainRead, AttestationDetail } from '@/lib/api/types'
import { formatDate, formatDateTime } from '@/lib/format'
import { formatMoney } from '@/lib/money'
import { networkDisplayName } from '@/lib/stellar/explorer'

import { AttestationStatusBadge } from './AttestationRows'

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-[0.8125rem] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  )
}

function ChainCheck({
  chain,
  attestation,
}: {
  chain: AttestationChainRead | null
  attestation: AttestationDetail
}) {
  let icon = <CircleAlert className="size-5 text-warning" aria-hidden />
  let title = 'Not read from the contract'
  let detail: ReactNode =
    'This server has no attestation registry configured, so the record could not be read.'
  if (chain?.error) {
    detail = `The contract could not be read right now: ${chain.error}`
  } else if (chain && !chain.found) {
    icon = <CircleX className="size-5 text-destructive" aria-hidden />
    title = 'Not found on-chain'
    detail = 'The registry has no record with this id.'
  } else if (chain && !chain.matches) {
    icon = <CircleX className="size-5 text-destructive" aria-hidden />
    title = 'Does not match the payout'
    detail = 'The record in the registry differs from the payout it should describe.'
  } else if (chain?.revoked) {
    icon = <CircleX className="size-5 text-destructive" aria-hidden />
    title = 'Revoked on-chain'
    detail = attestation.revocation_reason ?? 'The attester revoked this record.'
  } else if (chain) {
    icon = <CircleCheck className="size-5 text-success" aria-hidden />
    title = 'Matches the payout'
    detail = 'The registry holds this record, and its contributor, bounty, payout, token and amount match.'
  }
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3">
        {icon}
        <div className="min-w-0">
          <p className="text-sm font-medium">{title}</p>
          <p className="mt-1 text-[0.8125rem] leading-relaxed text-muted-foreground">{detail}</p>
        </div>
      </div>
      {chain && !chain.error && (
        <p className="text-xs text-muted-foreground">Read {formatDateTime(chain.checked_at)}</p>
      )}
    </div>
  )
}

function AttestationView({ a }: { a: AttestationDetail }) {
  return (
    <PageContainer className="pt-10 pb-16 sm:pt-14 sm:pb-20">
      <PageHeader
        size="display"
        eyebrow={<span className="label-mono">Attestation #{a.onchain_id}</span>}
        title={<span className="font-display font-bold">{a.bounty.title}</span>}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            <AttestationStatusBadge status={a.status} />
            <span>
              Completed by {a.contributor.display_name} on {formatDate(a.completed_at)}
            </span>
          </span>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-8">
        <Card className="gap-4">
          <CardHeader>
            <CardTitle>
              <h2>Recorded completion</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="divide-y">
              <Fact label="Contributor">
                <Link
                  to={`/u/${a.contributor.username}`}
                  className="inline-flex items-center gap-2 hover:underline"
                >
                  <UserAvatar user={a.contributor} className="size-6 text-[0.625rem]" />
                  {a.contributor.display_name}
                </Link>
              </Fact>
              <Fact label="Paid to">
                <MonoValue value={a.contributor_address} label="contributor wallet" className="-my-1" />
              </Fact>
              <Fact label="Bounty">
                <Link to={`/bounties/${a.bounty.slug || a.bounty.id}`} className="hover:underline">
                  {a.bounty.title}
                </Link>
              </Fact>
              <Fact label="Amount">
                <span className="amount">{formatMoney(a.amount, a.asset)}</span>
                {a.payments_count > 1 && (
                  <span className="text-muted-foreground"> across {a.payments_count} payments</span>
                )}
              </Fact>
              {a.first_paid_at && a.payments_count > 1 && (
                <Fact label="First paid">{formatDateTime(a.first_paid_at)}</Fact>
              )}
              <Fact label="Completed">{formatDateTime(a.completed_at)}</Fact>
              {a.attested_at && <Fact label="Attested">{formatDateTime(a.attested_at)}</Fact>}
              {a.revoked_at && (
                <Fact label="Revoked">
                  {formatDateTime(a.revoked_at)}
                  {a.revocation_reason ? `: ${a.revocation_reason}` : ''}
                </Fact>
              )}
              <Fact label="Completing payout">
                <MonoValue
                  value={a.payout_tx_hash}
                  label="payout transaction hash"
                  href={a.payout_explorer_url}
                  className="-my-1"
                />
              </Fact>
              <Fact label="Attestation transaction">
                <MonoValue
                  value={a.attestation_tx_hash}
                  label="attestation transaction hash"
                  href={a.attestation_explorer_url}
                  className="-my-1"
                />
              </Fact>
              <Fact label="Escrow contract">
                <MonoValue value={a.escrow_contract_id} label="escrow contract" className="-my-1" />
              </Fact>
              <Fact label="Escrow bounty id">
                <MonoValue value={a.onchain_bounty_id} label="escrow bounty id" className="-my-1" />
              </Fact>
              <Fact label="Token contract">
                <MonoValue value={a.token_contract_id} label="token contract" className="-my-1" />
              </Fact>
            </dl>
          </CardContent>
        </Card>
        <aside aria-label="On-chain check" className="space-y-6">
          <Card className="gap-4">
            <CardHeader>
              <CardTitle>
                <h2>Read from the contract</h2>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <ChainCheck chain={a.chain} attestation={a} />
              <div className="space-y-1 border-t pt-3">
                <p className="text-xs text-muted-foreground">
                  Attestation registry, {networkDisplayName(a.network)}
                </p>
                <MonoValue
                  value={a.contract_id}
                  label="attestation registry contract"
                  href={a.contract_explorer_url}
                  className="-my-1"
                />
              </div>
            </CardContent>
          </Card>
          <p className="px-1 text-[0.8125rem] text-muted-foreground">
            Holding a credential for this completion?{' '}
            <Link to="/credentials/verify" className="font-medium text-primary-emphasis hover:underline">
              Verify it
            </Link>
          </p>
        </aside>
      </div>
    </PageContainer>
  )
}

export default function AttestationPage() {
  const { attestationId } = useParams()
  const { data, isPending, isError, error, refetch } = useAttestation(attestationId)
  if (isError) {
    if (isApiError(error) && error.status === 404) return <NotFoundPage />
    return (
      <PageContainer className="py-16">
        <ErrorState error={error} title="Could not load this attestation" onRetry={() => refetch()} />
      </PageContainer>
    )
  }
  return (
    <Bones
      name="attestation-detail"
      loading={isPending}
      fallback={<LoadingState label="Reading the attestation" className="min-h-[60vh]" />}
    >
      {data && <AttestationView a={data} />}
    </Bones>
  )
}
