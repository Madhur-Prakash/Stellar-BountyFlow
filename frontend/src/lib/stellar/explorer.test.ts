import { describe, expect, it } from 'vitest'

import { transactionExplorerHref } from './explorer'

const config = {
  explorer_base_url: 'https://stellar.expert/explorer/testnet',
  blockchain_mode: 'testnet' as const,
  network: 'testnet',
}
const hash = 'a'.repeat(64)

describe('transactionExplorerHref', () => {
  it('links submitted transactions to the configured explorer', () => {
    expect(
      transactionExplorerHref({ transaction_hash: hash, explorer_url: null, status: 'CONFIRMED' }, config),
    ).toBe(`https://stellar.expert/explorer/testnet/tx/${hash}`)
  })

  it('never links transactions that were not submitted to the network', () => {
    for (const status of ['CREATED', 'SIGNATURE_REQUIRED', 'EXPIRED'] as const) {
      expect(
        transactionExplorerHref({ transaction_hash: hash, explorer_url: null, status }, config),
      ).toBeNull()
    }
  })
})
