import { describe, expect, it } from 'vitest'

import { ApiError } from '@/lib/api/client'

import { mapChainError } from './useChainAction'
import { WalletError } from './wallet'

describe('mapChainError', () => {
  it('maps wallet errors', () => {
    expect(mapChainError(new WalletError('USER_REJECTED', 'no')).kind).toBe('user_rejected')
    expect(mapChainError(new WalletError('WRONG_NETWORK', 'net')).kind).toBe('network_mismatch')
    expect(mapChainError(new WalletError('NOT_INSTALLED', 'x')).kind).toBe('wallet_not_installed')
  })

  it('maps API and on-chain failures', () => {
    const insufficient = new ApiError({
      status: 502,
      code: 'blockchain_error',
      message: 'op_underfunded: insufficient balance',
    })
    expect(mapChainError(insufficient).kind).toBe('insufficient_balance')
    const expired = new ApiError({
      status: 409,
      code: 'invalid_state_transition',
      message: 'Prepared transaction expired',
    })
    expect(mapChainError(expired).kind).toBe('expired')
    const contract = new ApiError({
      status: 502,
      code: 'blockchain_error',
      message: 'HostError: Error(Contract, #4)',
    })
    expect(mapChainError(contract).kind).toBe('contract_error')
    const other = new ApiError({
      status: 403,
      code: 'forbidden',
      message: 'Not your bounty',
      requestId: 'r1',
    })
    expect(mapChainError(other)).toMatchObject({
      kind: 'api_error',
      message: 'Not your bounty',
      detail: 'Request ID r1',
    })
  })
})

describe('mapChainError: structured API codes', () => {
  it('uses contract_rejected details instead of guessing from text', () => {
    const e = new ApiError({
      status: 422,
      code: 'contract_rejected',
      message: 'Contributors are still assigned on-chain.',
      extra: { contract_error: 'AssignmentsOutstanding' },
    })
    expect(mapChainError(e)).toMatchObject({
      kind: 'contract_error',
      detail: 'Contract error: AssignmentsOutstanding',
    })
  })

  it('treats wallet ownership problems as wallet errors', () => {
    const e = new ApiError({ status: 403, code: 'wallet_not_verified', message: 'x' })
    expect(mapChainError(e).kind).toBe('wallet_required')
  })
})
