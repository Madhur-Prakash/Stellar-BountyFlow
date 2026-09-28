/**
 * Wallet integration.
 *
 * Production uses Freighter (@stellar/freighter-api v6). Every Freighter call
 * resolves to `{ ...result, error?: FreighterApiError }` instead of throwing;
 * this module converts that into typed `WalletError`s. BountyFlow never asks
 * for, handles, or stores secret keys or seed phrases: signing always happens
 * inside the wallet.
 *
 * End-to-end tests cannot drive the Freighter extension, so a *test-only*
 * provider exists behind the same interface. It is active only when BOTH the
 * build flag `VITE_ENABLE_TEST_WALLET === "true"` is set (vite.config.ts
 * refuses to build production bundles with it) AND the test runner injected
 * `window.__BOUNTYFLOW_TEST_WALLET__`. The injected object signs through a
 * function exposed by the test process, so no secret key is ever in the page.
 *
 * `@stellar/freighter-api` is loaded on first use (`freighterApi()`), so pages
 * that never touch a wallet do not download it.
 */
import type freighterApiDefault from '@stellar/freighter-api'

export type WalletErrorCode =
  'NOT_INSTALLED' | 'USER_REJECTED' | 'WRONG_NETWORK' | 'ADDRESS_MISMATCH' | 'NOT_CONNECTED' | 'UNKNOWN'

export class WalletError extends Error {
  readonly code: WalletErrorCode
  readonly expected?: string
  readonly actual?: string

  constructor(code: WalletErrorCode, message: string, extra: { expected?: string; actual?: string } = {}) {
    super(message)
    this.name = 'WalletError'
    this.code = code
    this.expected = extra.expected
    this.actual = extra.actual
  }
}

export function isWalletError(e: unknown): e is WalletError {
  return e instanceof WalletError
}

export const FREIGHTER_INSTALL_URL = 'https://www.freighter.app/'

export type WalletNetwork = {
  /** Wallet network label, e.g. "TESTNET", "PUBLIC", "FUTURENET". */
  network: string
  networkPassphrase: string
  networkUrl: string
  sorobanRpcUrl?: string
}

/** What BountyFlow needs from a wallet; implemented by Freighter and by the E2E test provider. */
type WalletProvider = {
  name: string
  isInstalled(): Promise<boolean>
  /** Prompts (if needed) and returns the shared address. */
  requestAccess(): Promise<string>
  /** Current address without prompting; null when the site is not allowed yet. */
  getAddress(): Promise<string | null>
  getNetwork(): Promise<WalletNetwork>
  sign(
    xdr: string,
    opts: { networkPassphrase: string; address: string },
  ): Promise<{ signedXdr: string; signer: string | null }>
}

// ---------------------------------------------------------------------------
// Freighter
// ---------------------------------------------------------------------------

type FreighterErrorLike = { code?: number; message?: string } | undefined

const REJECT_RE = /(reject|declin|denied|cancel)/i

function toWalletError(err: FreighterErrorLike, fallback: string): WalletError {
  const message = err?.message ?? fallback
  // Freighter uses code -4 for "user declined" and wording like "The user rejected this request".
  if (err?.code === -4 || REJECT_RE.test(message)) {
    return new WalletError('USER_REJECTED', 'You rejected the request in Freighter.')
  }
  if (/not (installed|found)|no .*extension/i.test(message)) {
    return new WalletError('NOT_INSTALLED', 'Freighter is not installed in this browser.')
  }
  return new WalletError('UNKNOWN', message || fallback)
}

type FreighterApi = typeof freighterApiDefault

let freighterModule: Promise<FreighterApi> | null = null

/** Loads the Freighter SDK once, on first use. A failed load is retried on the next call. */
function freighterApi(): Promise<FreighterApi> {
  freighterModule ??= import('@stellar/freighter-api')
    .then((m): FreighterApi => (typeof m.isConnected === 'function' ? m : m.default))
    .catch((e: unknown) => {
      freighterModule = null
      throw e
    })
  return freighterModule
}

const freighter: WalletProvider = {
  name: 'Freighter',
  async isInstalled() {
    try {
      const res = await (await freighterApi()).isConnected()
      return !res.error && res.isConnected
    } catch {
      return false
    }
  },
  async requestAccess() {
    const res = await (await freighterApi()).requestAccess()
    if (res.error) throw toWalletError(res.error, 'Could not connect to Freighter.')
    if (!res.address) throw new WalletError('USER_REJECTED', 'Freighter did not share an address.')
    return res.address
  },
  async getAddress() {
    const res = await (await freighterApi()).getAddress()
    if (res.error || !res.address) return null
    return res.address
  },
  async getNetwork() {
    const res = await (await freighterApi()).getNetworkDetails()
    if (res.error) throw toWalletError(res.error, 'Could not read the Freighter network.')
    return {
      network: res.network,
      networkPassphrase: res.networkPassphrase,
      networkUrl: res.networkUrl,
      sorobanRpcUrl: res.sorobanRpcUrl,
    }
  },
  async sign(xdr, { networkPassphrase, address }) {
    const res = await (await freighterApi()).signTransaction(xdr, { networkPassphrase, address })
    if (res.error) throw toWalletError(res.error, 'Freighter could not sign the transaction.')
    if (!res.signedTxXdr) throw new WalletError('USER_REJECTED', 'The transaction was not signed.')
    return { signedXdr: res.signedTxXdr, signer: res.signerAddress ?? null }
  },
}

// ---------------------------------------------------------------------------
// E2E test provider (never active in production builds)
// ---------------------------------------------------------------------------

/** Shape injected by Playwright (`page.addInitScript`). */
export type InjectedTestWallet = {
  /** Optional display name (defaults to "Test wallet"). */
  name?: string
  publicKey: string
  network: string
  networkPassphrase: string
  signTransaction: (xdr: string) => Promise<string>
}

declare global {
  interface Window {
    __BOUNTYFLOW_TEST_WALLET__?: InjectedTestWallet
  }
}

const TEST_WALLET_ENABLED = import.meta.env.VITE_ENABLE_TEST_WALLET === 'true'

function injectedTestWallet(): InjectedTestWallet | null {
  if (!TEST_WALLET_ENABLED || typeof window === 'undefined') return null
  return window.__BOUNTYFLOW_TEST_WALLET__ ?? null
}

function testProvider(w: InjectedTestWallet): WalletProvider {
  return {
    name: w.name ?? 'Test wallet',
    isInstalled: async () => true,
    requestAccess: async () => w.publicKey,
    getAddress: async () => w.publicKey,
    getNetwork: async () => ({ network: w.network, networkPassphrase: w.networkPassphrase, networkUrl: '' }),
    sign: async (xdr) => ({ signedXdr: await w.signTransaction(xdr), signer: w.publicKey }),
  }
}

function provider(): WalletProvider {
  const test = injectedTestWallet()
  return test ? testProvider(test) : freighter
}

/** Display name of the active wallet ("Freighter" in every real build). */
export function walletProviderName(): string {
  return provider().name
}

// ---------------------------------------------------------------------------
// Public API (unchanged for callers)
// ---------------------------------------------------------------------------

/** Is a wallet installed (and reachable from this page)? */
export async function isFreighterInstalled(): Promise<boolean> {
  return provider().isInstalled()
}

async function assertInstalled() {
  if (!(await isFreighterInstalled())) {
    throw new WalletError('NOT_INSTALLED', 'Freighter is not installed in this browser.')
  }
}

/** Prompts the user (if needed) to share their public key with this site. */
export async function connectWallet(): Promise<string> {
  await assertInstalled()
  return provider().requestAccess()
}

/** Returns the current address without prompting; null when the site is not allowed yet. */
export async function getWalletAddress(): Promise<string | null> {
  if (!(await isFreighterInstalled())) return null
  return provider().getAddress()
}

export async function getWalletNetwork(): Promise<WalletNetwork> {
  await assertInstalled()
  return provider().getNetwork()
}

/** Throws WRONG_NETWORK when the wallet is not on the passphrase the API expects. */
export async function assertWalletNetwork(expectedPassphrase: string): Promise<WalletNetwork> {
  const net = await getWalletNetwork()
  if (net.networkPassphrase !== expectedPassphrase) {
    throw new WalletError(
      'WRONG_NETWORK',
      `Freighter is on ${net.network || 'another network'}. Switch Freighter to the network shown in BountyFlow and try again.`,
      { expected: expectedPassphrase, actual: net.networkPassphrase },
    )
  }
  return net
}

export type SignOptions = { networkPassphrase: string; address: string }

/**
 * Signs a transaction XDR in the wallet after verifying the network and the
 * active account. Returns the signed XDR (the API submits it).
 */
export async function signTransaction(
  xdr: string,
  { networkPassphrase, address }: SignOptions,
): Promise<string> {
  await assertInstalled()
  await assertWalletNetwork(networkPassphrase)
  const { signedXdr, signer } = await provider().sign(xdr, { networkPassphrase, address })
  if (signer && signer !== address) {
    throw new WalletError(
      'ADDRESS_MISMATCH',
      'The wallet signed with a different account than the one selected.',
      {
        expected: address,
        actual: signer,
      },
    )
  }
  return signedXdr
}

/** Human label for a network passphrase. */
export function networkLabelFromPassphrase(passphrase: string | null | undefined): string {
  if (!passphrase) return 'Unknown'
  if (passphrase.startsWith('Test SDF Network')) return 'Testnet'
  if (passphrase.startsWith('Public Global Stellar Network')) return 'Mainnet'
  if (passphrase.startsWith('Test SDF Future Network')) return 'Futurenet'
  return 'Custom'
}

export function walletErrorMessage(e: unknown): string {
  if (isWalletError(e)) return e.message
  if (e instanceof Error) return e.message
  return 'Wallet request failed.'
}
