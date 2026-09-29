import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Attestation, VerificationReport } from '@/lib/api/types'
import { renderWithProviders } from '@/test/render'

import { AttestationRows, AttestationStatusBadge } from './AttestationRows'

const XLM = {
  code: 'XLM',
  issuer: null,
  type: 'native' as const,
  contract_id: 'CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC',
  identifier: 'native',
  decimals: 7,
}

const USDC = {
  code: 'USDC',
  issuer: 'GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5',
  type: 'credit_alphanum4' as const,
  contract_id: 'CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA',
  identifier: 'USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5',
  decimals: 7,
}

function attestation(overrides: Partial<Attestation> = {}): Attestation {
  return {
    id: '2b0d1b1e-0000-4000-8000-000000000001',
    onchain_id: 7,
    status: 'CONFIRMED',
    network: 'testnet',
    contributor: { id: 'u1', username: 'kai-tanaka', display_name: 'Kai Tanaka', avatar_url: null },
    contributor_address: 'GDGKUNW2PI2EIHVWJ5RXLBFP2E5WLOJUS7ONVBJEOAW6AXH7RIU7ARCU',
    bounty: { id: 'b1', slug: 'escrow-widget', title: 'Escrow status widget' },
    amount: '12.5000000',
    asset: XLM,
    payments_count: 1,
    first_paid_at: null,
    completed_at: '2026-09-20T10:00:00Z',
    attested_at: '2026-09-20T10:01:00Z',
    confirmed_at: '2026-09-20T10:01:30Z',
    payout_tx_hash: 'a'.repeat(64),
    payout_explorer_url: `https://stellar.expert/explorer/testnet/tx/${'a'.repeat(64)}`,
    attestation_tx_hash: 'b'.repeat(64),
    attestation_explorer_url: `https://stellar.expert/explorer/testnet/tx/${'b'.repeat(64)}`,
    contract_id: 'CBXJVFUQHWECJZQSEBAFGHXLHP72PCPUX7XES42KVEMVAMZ26D5CZ33N',
    contract_explorer_url:
      'https://stellar.expert/explorer/testnet/contract/CBXJVFUQHWECJZQSEBAFGHXLHP72PCPUX7XES42KVEMVAMZ26D5CZ33N',
    escrow_contract_id: 'CBCXG46FJPYBPWYZ24BWFVNJ6G2ILFAXHX2COETDNXYE6C5IJWAZ3M4C',
    onchain_bounty_id: 'c'.repeat(64),
    token_contract_id: XLM.contract_id!,
    revoked_at: null,
    revocation_reason: null,
    ...overrides,
  }
}

describe('attestation rows', () => {
  it('shows the amount in the bounty’s own asset, never a default of XLM', () => {
    renderWithProviders(
      <AttestationRows
        label="Completions"
        items={[
          attestation(),
          attestation({
            id: 'usdc-row',
            onchain_id: 8,
            amount: '250.0000000',
            asset: USDC,
            bounty: { id: 'b2', slug: 'usdc-audit', title: 'USDC audit' },
          }),
        ]}
      />,
    )
    expect(screen.getByText('12.5 XLM')).toBeInTheDocument()
    expect(screen.getByText('250 USDC')).toBeInTheDocument()
  })

  it('counts the transfers that paid a completion when there was more than one', () => {
    renderWithProviders(
      <AttestationRows
        label="Completions"
        items={[attestation({ payments_count: 3, amount: '30.0000000' })]}
      />,
    )
    expect(screen.getByText('3 payments')).toBeInTheDocument()
  })

  it('links the attestation and the payout to the explorer', () => {
    renderWithProviders(<AttestationRows label="Completions" items={[attestation()]} />)
    const row = screen.getByRole('listitem')
    expect(within(row).getByRole('link', { name: 'Attestation #7' })).toHaveAttribute(
      'href',
      '/attestations/7',
    )
    const explorer = within(row).getAllByRole('link', { name: /stellar explorer/i })
    expect(explorer.map((a) => a.getAttribute('href'))).toEqual([
      `https://stellar.expert/explorer/testnet/tx/${'b'.repeat(64)}`,
      `https://stellar.expert/explorer/testnet/tx/${'a'.repeat(64)}`,
    ])
  })

  it('keeps a revoked completion visible with its reason', () => {
    renderWithProviders(
      <AttestationRows
        label="Completions"
        items={[
          attestation({
            status: 'REVOKED',
            revoked_at: '2026-09-21T09:00:00Z',
            revocation_reason: 'Recorded for the wrong contributor',
          }),
        ]}
      />,
    )
    expect(screen.getByText('Revoked')).toBeInTheDocument()
    expect(screen.getByText('Recorded for the wrong contributor')).toBeInTheDocument()
  })

  it('does not claim a completion is on-chain before it is recorded', () => {
    renderWithProviders(
      <AttestationRows
        label="Completions"
        items={[
          attestation({
            status: 'PENDING',
            onchain_id: null,
            attestation_tx_hash: null,
            attestation_explorer_url: null,
          }),
        ]}
      />,
    )
    expect(screen.getByText('Recording on-chain')).toBeInTheDocument()
    expect(screen.queryByText('Completed on-chain')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /attestation #/i })).not.toBeInTheDocument()
  })
})

describe('attestation status badge', () => {
  it.each([
    ['CONFIRMED', 'Completed on-chain'],
    ['SUBMITTED', 'Recording on-chain'],
    ['REVOKING', 'Revoking'],
    ['REVOKED', 'Revoked'],
    ['FAILED', 'Not recorded'],
  ] as const)('%s reads as "%s"', (status, label) => {
    renderWithProviders(<AttestationStatusBadge status={status} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })
})

describe('verification report shape', () => {
  it('names every check the API returns', () => {
    const report: VerificationReport = {
      verified: false,
      checks: [
        { id: 'format', label: 'Credential format', status: 'pass', detail: 'Verifiable Credential 2.0.' },
        { id: 'issuer', label: 'Issuer', status: 'pass', detail: 'Issued by BountyFlow.' },
        { id: 'signature', label: 'Signature', status: 'pass', detail: 'The proof verifies.' },
        { id: 'validity', label: 'Validity period', status: 'pass', detail: 'Valid since 2026-09-20.' },
        { id: 'status', label: 'Revocation status', status: 'fail', detail: 'Revoked on 2026-09-21.' },
        { id: 'attestation', label: 'On-chain attestation', status: 'fail', detail: 'Revoked on-chain.' },
      ],
      credential_id: 'urn:uuid:0d2a2a1e-0000-4000-8000-000000000001',
      kind: 'completion',
      issuer: { id: 'did:web:bountyflow.test', name: 'BountyFlow', is_this_site: true },
      subject: 'did:pkh:stellar:testnet:GDGKUNW2PI2EIHVWJ5RXLBFP2E5WLOJUS7ONVBJEOAW6AXH7RIU7ARCU',
      valid_from: '2026-09-20T10:02:00Z',
      attestations: [],
      checked_at: '2026-09-21T09:05:00Z',
    }
    expect(report.checks.filter((c) => c.status === 'fail')).toHaveLength(2)
    expect(report.verified).toBe(false)
  })
})
