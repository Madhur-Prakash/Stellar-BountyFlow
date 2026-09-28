import { describe, expect, it } from 'vitest'

import type { BlockchainTransaction } from '../types'
import { onchainAssignees } from './chain'

const tx = (overrides: Partial<BlockchainTransaction>): BlockchainTransaction => ({
  id: Math.random().toString(36),
  bounty_id: 'b1',
  bounty_title: 'B',
  user: null,
  transaction_hash: 'SIM-1',
  transaction_type: 'ASSIGN',
  network: 'testnet',
  amount: null,
  asset: null,
  status: 'CONFIRMED',
  source_address: 'GREQ',
  destination_address: 'GCON1',
  ledger_sequence: 1,
  submitted_at: null,
  confirmed_at: '2026-09-25T10:00:00Z',
  failure_reason: null,
  explorer_url: null,
  created_at: '2026-09-25T10:00:00Z',
  ...overrides,
})

describe('onchainAssignees', () => {
  it('replays confirmed ASSIGN / PAYOUT / CANCEL_CONSENT transactions', () => {
    const set = onchainAssignees([
      tx({ destination_address: 'GCON1', confirmed_at: '2026-09-25T10:00:00Z' }),
      tx({ destination_address: 'GCON2', confirmed_at: '2026-09-25T10:01:00Z' }),
      tx({ transaction_type: 'PAYOUT', destination_address: 'GCON1', confirmed_at: '2026-09-25T11:00:00Z' }),
      tx({
        transaction_type: 'CANCEL_CONSENT',
        source_address: 'GCON2',
        destination_address: null,
        confirmed_at: '2026-09-25T12:00:00Z',
      }),
      tx({ destination_address: 'GCON3', status: 'FAILED' }),
    ])
    expect([...set]).toEqual([])
    expect([...onchainAssignees([tx({ destination_address: 'GCON9' })])]).toEqual(['GCON9'])
    expect(onchainAssignees(undefined).size).toBe(0)
  })
})
