import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  forgetWallet,
  isWalletError,
  networkLabelFromPassphrase,
  restoreWallet,
  selectedWalletId,
  selectWallet,
  signMessage,
  signTransaction,
  TEST_WALLET_ID,
  walletErrorMessage,
  walletProviderName,
  type InjectedTestWallet,
} from './wallet'

const TESTNET = 'Test SDF Network ; September 2015'
const ADDRESS = 'GA2H4I5DEBKXY6AERRHVXO2YL2FDIQTJK7K65577H724EANX4TBQ4BGQ'

function injectWallet(overrides: Partial<InjectedTestWallet> = {}) {
  window.__BOUNTYFLOW_TEST_WALLET__ = {
    name: 'Test wallet',
    publicKey: ADDRESS,
    network: 'TESTNET',
    networkPassphrase: TESTNET,
    signTransaction: vi.fn(async (xdr: string) => `${xdr}:signed`),
    signMessage: vi.fn(async () => 'c2lnbmF0dXJl'),
    ...overrides,
  }
}

// Any wallet the kit knows is reached through a dynamic import of the kit itself, and Vite transforms that
// bundle the first time a test asks for one. On a loaded machine that transform alone can outrun a test's
// default 5s budget, which made whichever test happened to be first fail intermittently. Paying for it once,
// up front and with room to spare, keeps the tests themselves measuring what they mean to.
beforeAll(async () => {
  vi.stubEnv('VITE_ENABLE_TEST_WALLET', 'true')
  await selectWallet(TEST_WALLET_ID).catch(() => {})
  forgetWallet()
  vi.unstubAllEnvs()
}, 60_000)

beforeEach(() => {
  // The kit-compatible test provider is the one E2E uses; it only exists behind this build flag.
  vi.stubEnv('VITE_ENABLE_TEST_WALLET', 'true')
  window.localStorage.clear()
  forgetWallet()
  injectWallet()
})

afterEach(() => {
  delete window.__BOUNTYFLOW_TEST_WALLET__
  forgetWallet()
  window.localStorage.clear()
  vi.unstubAllEnvs()
})

describe('choosing a wallet', () => {
  it('connects the chosen wallet and remembers it for the next visit', async () => {
    expect(selectedWalletId()).toBeNull()

    const address = await selectWallet(TEST_WALLET_ID)
    expect(address).toBe(ADDRESS)
    expect(selectedWalletId()).toBe(TEST_WALLET_ID)
    expect(walletProviderName()).toBe('Test wallet')
    expect(window.localStorage.getItem('bf-wallet')).toContain(TEST_WALLET_ID)

    // A fresh page load restores it without prompting.
    forgetWalletInMemoryOnly()
    expect(await restoreWallet()).toBe(ADDRESS)
    expect(selectedWalletId()).toBe(TEST_WALLET_ID)
  })

  it('forgets the wallet on disconnect', async () => {
    await selectWallet(TEST_WALLET_ID)
    forgetWallet()
    expect(selectedWalletId()).toBeNull()
    expect(window.localStorage.getItem('bf-wallet')).toBeNull()
  })

  it('refuses a wallet that is not available in this browser', async () => {
    await expect(selectWallet('a-wallet-that-does-not-exist')).rejects.toMatchObject({
      code: 'NOT_INSTALLED',
    })
  })
})

describe('signing', () => {
  it('signs a transaction after checking the network', async () => {
    await selectWallet(TEST_WALLET_ID)
    const signed = await signTransaction('AAAA', { networkPassphrase: TESTNET, address: ADDRESS })
    expect(signed).toBe('AAAA:signed')
  })

  it('refuses to sign when the wallet is on another network', async () => {
    await selectWallet(TEST_WALLET_ID)
    await expect(
      signTransaction('AAAA', {
        networkPassphrase: 'Public Global Stellar Network ; September 2015',
        address: ADDRESS,
      }),
    ).rejects.toMatchObject({ code: 'WRONG_NETWORK' })
  })

  it('refuses a signature from another account', async () => {
    injectWallet({
      signTransaction: vi.fn(async (xdr: string) => `${xdr}:signed`),
      publicKey: ADDRESS,
    })
    await selectWallet(TEST_WALLET_ID)
    await expect(
      signTransaction('AAAA', { networkPassphrase: TESTNET, address: 'GDIFFERENTADDRESS' }),
    ).rejects.toMatchObject({ code: 'ADDRESS_MISMATCH' })
  })

  it('signs a SEP-53 message when the wallet supports it', async () => {
    await selectWallet(TEST_WALLET_ID)
    const signature = await signMessage('BountyFlow wallet verification', {
      networkPassphrase: TESTNET,
      address: ADDRESS,
    })
    expect(signature).toBe('c2lnbmF0dXJl')
  })

  it('reports a wallet that cannot sign messages instead of failing silently', async () => {
    injectWallet({ signMessage: undefined })
    await selectWallet(TEST_WALLET_ID)
    await expect(signMessage('x', { networkPassphrase: TESTNET, address: ADDRESS })).rejects.toMatchObject({
      code: 'UNSUPPORTED',
    })
  })

  it('requires a wallet before signing anything', async () => {
    await expect(
      signTransaction('AAAA', { networkPassphrase: TESTNET, address: ADDRESS }),
    ).rejects.toMatchObject({ code: 'NOT_CONNECTED' })
  })
})

describe('errors and labels', () => {
  it('names the networks users see', () => {
    expect(networkLabelFromPassphrase(TESTNET)).toBe('Testnet')
    expect(networkLabelFromPassphrase('Public Global Stellar Network ; September 2015')).toBe('Mainnet')
    expect(networkLabelFromPassphrase(null)).toBe('Unknown')
  })

  it('describes wallet failures for the UI', async () => {
    try {
      await signTransaction('AAAA', { networkPassphrase: TESTNET, address: ADDRESS })
    } catch (e) {
      expect(isWalletError(e)).toBe(true)
      expect(walletErrorMessage(e)).toBe('Choose a wallet first.')
    }
    expect(walletErrorMessage(new Error('boom'))).toBe('boom')
    expect(walletErrorMessage('nope')).toBe('Wallet request failed.')
  })
})

/** Drops the in-memory provider the way a page reload does, keeping what localStorage remembers. */
function forgetWalletInMemoryOnly() {
  const remembered = window.localStorage.getItem('bf-wallet')
  forgetWallet()
  if (remembered) window.localStorage.setItem('bf-wallet', remembered)
}
