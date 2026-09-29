/**
 * Wallet integration: every Stellar wallet the Stellar Wallets Kit supports, plus BountyFlow passkey wallets.
 *
 * The kit's modules (Freighter, xBull, Albedo, LOBSTR, Hana and the others that need no API keys) are loaded
 * on first use from the lazy `wallet-kit` chunk; passkey-kit loads from the lazy `passkey` chunk. The user picks
 * a wallet in `WalletPickerDialog`; the choice (wallet id and address, both public) is remembered in this
 * browser. BountyFlow never asks for, handles or stores secret keys or seed phrases: signing always happens in
 * the wallet.
 *
 * End-to-end tests cannot drive browser extensions, so a *test-only* wallet exists behind the same
 * kit `ModuleInterface`. It is active only when BOTH the build flag `VITE_ENABLE_TEST_WALLET === "true"` is set
 * (vite.config.ts refuses to build production bundles with it) AND the test runner injected
 * `window.__BOUNTYFLOW_TEST_WALLET__`. The injected object signs through a function exposed by the test
 * process, so no secret key is ever in the page.
 */
import type { ModuleInterface } from '@creit.tech/stellar-wallets-kit/types'

import type * as PasskeyChunk from './passkey'
import type * as WalletKitChunk from './wallet-kit'

export type WalletErrorCode =
  | 'NOT_INSTALLED'
  | 'USER_REJECTED'
  | 'WRONG_NETWORK'
  | 'ADDRESS_MISMATCH'
  | 'NOT_CONNECTED'
  | 'UNSUPPORTED'
  | 'UNKNOWN'

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

/** Kit product ids, plus BountyFlow's own wallets. */
export type WalletId = string
export const TEST_WALLET_ID = 'bountyflow-test'
export const PASSKEY_WALLET_ID = 'passkey'

/** How a wallet proves ownership of an account: a SEP-10 challenge transaction or a SEP-53 signed message. */
export type AccountProof = 'transaction' | 'message'

export type WalletKind = 'extension' | 'web' | 'passkey' | 'test'

export type WalletOption = {
  id: WalletId
  name: string
  /** Where to get the wallet (install link). */
  url: string
  kind: WalletKind
  /** Installed in this browser, or usable without installing (web wallets). */
  available: boolean
}

type CatalogEntry = { name: string; url: string; kind: WalletKind; proof?: AccountProof }

/**
 * Wallets BountyFlow lists first, with their install pages. Other kit modules follow in the kit's order.
 * LOBSTR cannot be told which network to sign for, so it proves ownership with a signed message.
 */
const CATALOG: Record<string, CatalogEntry> = {
  freighter: { name: 'Freighter', url: FREIGHTER_INSTALL_URL, kind: 'extension' },
  xbull: { name: 'xBull', url: 'https://xbull.app', kind: 'web' },
  albedo: { name: 'Albedo', url: 'https://albedo.link', kind: 'web' },
  lobstr: { name: 'LOBSTR', url: 'https://lobstr.co', kind: 'extension', proof: 'message' },
  hana: { name: 'Hana Wallet', url: 'https://hanawallet.io', kind: 'extension' },
}

export const FEATURED_WALLETS = Object.keys(CATALOG)

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

/** What BountyFlow needs from a wallet; implemented over kit modules, the test wallet and passkey wallets. */
type WalletProvider = {
  id: WalletId
  name: string
  proof: AccountProof
  /** Where to get this wallet, for the picker's install link. Empty when there is nowhere to send people. */
  url: string
  isInstalled(): Promise<boolean>
  /** Prompts (if needed) and returns the shared address. */
  requestAccess(): Promise<string>
  /** Current address without prompting; null when unknown until the user connects. */
  getAddress(): Promise<string | null>
  /** The wallet's network, or null when the wallet cannot report it. */
  getNetwork(): Promise<WalletNetwork | null>
  sign(xdr: string, opts: SignOptions): Promise<{ signedXdr: string; signer: string | null }>
  signMessage?(message: string, opts: SignOptions): Promise<{ signature: string; signer: string | null }>
}

type KitError = { code?: number; message?: string } | undefined

const REJECT_RE = /(reject|declin|denied|cancel|closed)/i
const UNSUPPORTED_RE = /does not support/i

function toWalletError(err: unknown, wallet: string, fallback: string): WalletError {
  if (isWalletError(err)) return err
  const e = err as KitError
  const message = (e?.message ?? (err instanceof Error ? err.message : undefined) ?? fallback).toString()
  // Freighter uses code -4 for "user declined"; others word it ("The user rejected this request").
  if (e?.code === -4 || REJECT_RE.test(message)) {
    return new WalletError('USER_REJECTED', `You rejected the request in ${wallet}.`)
  }
  if (UNSUPPORTED_RE.test(message)) return new WalletError('UNSUPPORTED', message)
  if (/not (installed|connected|found)|no .*extension/i.test(message)) {
    return new WalletError('NOT_INSTALLED', `${wallet} is not installed in this browser.`)
  }
  return new WalletError('UNKNOWN', message || fallback)
}

function withTimeout<T>(promise: Promise<T>, ms: number, fallback: T): Promise<T> {
  return Promise.race([promise, new Promise<T>((resolve) => setTimeout(() => resolve(fallback), ms))])
}

function base64(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  let s = ''
  for (const b of view) s += String.fromCharCode(b)
  return btoa(s)
}

/** A Stellar Wallets Kit module (or the kit-compatible test wallet) as a provider. */
function moduleProvider(mod: ModuleInterface, overrides: Partial<CatalogEntry> = {}): WalletProvider {
  const catalog = CATALOG[mod.productId]
  const name = overrides.name ?? catalog?.name ?? mod.productName
  const silent = mod.productId === 'freighter' || mod.productId === TEST_WALLET_ID
  return {
    id: mod.productId,
    name,
    // The kit publishes a product URL for its modules; the catalog only overrides the featured few.
    url: overrides.url ?? catalog?.url ?? mod.productUrl ?? '',
    proof: overrides.proof ?? catalog?.proof ?? 'transaction',
    isInstalled: () =>
      withTimeout(
        mod.isAvailable().catch(() => false),
        1000,
        false,
      ),
    async requestAccess() {
      try {
        const { address } = await mod.getAddress()
        if (!address) throw new WalletError('USER_REJECTED', `${name} did not share an address.`)
        return address
      } catch (e) {
        throw toWalletError(e, name, `Could not connect to ${name}.`)
      }
    },
    async getAddress() {
      // Only wallets that can answer without a prompt are asked; the others keep the remembered address.
      if (!silent) return null
      try {
        const { address } = await mod.getAddress({ skipRequestAccess: true })
        return address || null
      } catch {
        return null
      }
    },
    async getNetwork() {
      try {
        const net = await mod.getNetwork()
        return { network: net.network, networkPassphrase: net.networkPassphrase, networkUrl: '' }
      } catch {
        return null // e.g. xBull, Albedo, LOBSTR and Hana cannot report their network
      }
    },
    async sign(xdr, { networkPassphrase, address }) {
      try {
        const res = await mod.signTransaction(xdr, { networkPassphrase, address })
        if (!res.signedTxXdr) throw new WalletError('USER_REJECTED', 'The transaction was not signed.')
        return { signedXdr: res.signedTxXdr, signer: res.signerAddress ?? null }
      } catch (e) {
        throw toWalletError(e, name, `${name} could not sign the transaction.`)
      }
    },
    async signMessage(message, { networkPassphrase, address }) {
      try {
        const res = await mod.signMessage(message, { networkPassphrase, address })
        const raw = (res as { signedMessage?: unknown }).signedMessage
        const signature =
          typeof raw === 'string'
            ? raw
            : raw instanceof Uint8Array || raw instanceof ArrayBuffer
              ? base64(raw)
              : ''
        if (!signature) throw new WalletError('USER_REJECTED', 'The message was not signed.')
        return { signature, signer: res.signerAddress ?? null }
      } catch (e) {
        throw toWalletError(e, name, `${name} could not sign the message.`)
      }
    },
  }
}

let kitChunk: Promise<typeof WalletKitChunk> | null = null

/** Loads the kit modules once, on first use. A failed load is retried on the next call. */
function loadKit(): Promise<typeof WalletKitChunk> {
  kitChunk ??= import('./wallet-kit').catch((e: unknown) => {
    kitChunk = null
    throw e
  })
  return kitChunk
}

async function kitProviders(): Promise<WalletProvider[]> {
  const { kitModules } = await loadKit()
  return kitModules().map((m) => moduleProvider(m))
}

// ---------------------------------------------------------------------------
// E2E test wallet (never active in production builds)
// ---------------------------------------------------------------------------

/** Shape injected by Playwright (`page.addInitScript`). */
export type InjectedTestWallet = {
  /** Optional display name (defaults to "Test wallet"). */
  name?: string
  publicKey: string
  network: string
  networkPassphrase: string
  signTransaction: (xdr: string) => Promise<string>
  /** SEP-53: base64 ed25519 signature of sha256("Stellar Signed Message:\n" + message). */
  signMessage?: (message: string) => Promise<string>
  /** Prove ownership with a signed message instead of a challenge transaction. */
  proof?: AccountProof
  /** Connect without the picker on page load (default true), as a remembered wallet would. */
  autoConnect?: boolean
}

declare global {
  interface Window {
    __BOUNTYFLOW_TEST_WALLET__?: InjectedTestWallet
  }
}

/** Vite replaces this expression at build time, so a production bundle drops the test provider entirely. */
function testWalletEnabled(): boolean {
  return import.meta.env.VITE_ENABLE_TEST_WALLET === 'true'
}

function injectedTestWallet(): InjectedTestWallet | null {
  if (!testWalletEnabled() || typeof window === 'undefined') return null
  return window.__BOUNTYFLOW_TEST_WALLET__ ?? null
}

/** The injected test wallet as a Stellar Wallets Kit module, so it runs through exactly the same adapter. */
function testModule(w: InjectedTestWallet): ModuleInterface {
  return {
    moduleType: 'HOT_WALLET' as ModuleInterface['moduleType'],
    productId: TEST_WALLET_ID,
    productName: w.name ?? 'Test wallet',
    productUrl: 'https://developers.stellar.org',
    productIcon: '',
    isAvailable: async () => true,
    getAddress: async () => ({ address: w.publicKey }),
    getNetwork: async () => ({ network: w.network, networkPassphrase: w.networkPassphrase }),
    signTransaction: async (xdr) => ({
      signedTxXdr: await w.signTransaction(xdr),
      signerAddress: w.publicKey,
    }),
    signAuthEntry: async () => {
      throw { code: -3, message: 'The test wallet does not support the "signAuthEntry" function' }
    },
    signMessage: async (message) => {
      if (!w.signMessage)
        throw { code: -3, message: 'The test wallet does not support the "signMessage" function' }
      return { signedMessage: await w.signMessage(message), signerAddress: w.publicKey }
    },
  }
}

function testProvider(): WalletProvider | null {
  const w = injectedTestWallet()
  return w ? moduleProvider(testModule(w), { name: w.name ?? 'Test wallet', proof: w.proof }) : null
}

/** The test wallet should connect on load (fresh E2E browser contexts have no remembered choice). */
export function testWalletAutoConnects(): boolean {
  const w = injectedTestWallet()
  return !!w && w.autoConnect !== false
}

// ---------------------------------------------------------------------------
// Passkey smart wallets (C... contract accounts)
// ---------------------------------------------------------------------------

export type PasskeyWalletRef = {
  contractId: string
  keyId: string
  rpcUrl: string
  networkPassphrase: string
  walletWasmHash: string
}

let passkeyChunk: Promise<typeof PasskeyChunk> | null = null

/** Loads passkey-kit once, on first use. */
export function loadPasskeyKit(): Promise<typeof PasskeyChunk> {
  passkeyChunk ??= import('./passkey').catch((e: unknown) => {
    passkeyChunk = null
    throw e
  })
  return passkeyChunk
}

function passkeyError(e: unknown): WalletError {
  const message = e instanceof Error ? e.message : String(e)
  const cause = (e as { context?: { cause?: string }; cause?: unknown })?.context?.cause ?? ''
  if (/NotAllowedError|abort|cancel|timed out/i.test(`${message} ${String(cause)}`)) {
    return new WalletError('USER_REJECTED', 'The passkey request was cancelled.')
  }
  return new WalletError('UNKNOWN', message || 'The passkey could not sign.')
}

function passkeyProvider(ref: PasskeyWalletRef): WalletProvider {
  const config = {
    rpcUrl: ref.rpcUrl,
    networkPassphrase: ref.networkPassphrase,
    walletWasmHash: ref.walletWasmHash,
  }
  return {
    id: PASSKEY_WALLET_ID,
    // Nothing to install: the passkey is created in the browser, so there is nowhere to send anyone.
    url: '',
    name: 'Passkey wallet',
    proof: 'transaction',
    isInstalled: async () => typeof window !== 'undefined' && !!window.PublicKeyCredential,
    requestAccess: async () => ref.contractId,
    getAddress: async () => ref.contractId,
    getNetwork: async () => ({
      network: '',
      networkPassphrase: ref.networkPassphrase,
      networkUrl: ref.rpcUrl,
    }),
    async sign(xdr) {
      try {
        const { signTransactionAuth } = await loadPasskeyKit()
        return {
          signedXdr: await signTransactionAuth(config, xdr, ref.contractId, ref.keyId),
          signer: ref.contractId,
        }
      } catch (e) {
        throw passkeyError(e)
      }
    },
  }
}

// ---------------------------------------------------------------------------
// The chosen wallet (remembered in this browser)
// ---------------------------------------------------------------------------

const CHOICE_KEY = 'bf-wallet'

type Choice = { id: WalletId; address: string | null; passkey?: PasskeyWalletRef }

function readChoice(): Choice | null {
  try {
    const raw = window.localStorage.getItem(CHOICE_KEY)
    const parsed = raw ? (JSON.parse(raw) as Choice) : null
    return parsed && typeof parsed.id === 'string' ? parsed : null
  } catch {
    return null
  }
}

function writeChoice(choice: Choice | null) {
  try {
    if (choice) window.localStorage.setItem(CHOICE_KEY, JSON.stringify(choice))
    else window.localStorage.removeItem(CHOICE_KEY)
  } catch {
    /* storage unavailable: the choice simply is not remembered */
  }
}

let active: { provider: WalletProvider; address: string | null } | null = null

async function providerFor(id: WalletId, passkey?: PasskeyWalletRef): Promise<WalletProvider | null> {
  if (id === TEST_WALLET_ID) return testProvider()
  if (id === PASSKEY_WALLET_ID) return passkey ? passkeyProvider(passkey) : null
  return (await kitProviders()).find((p) => p.id === id) ?? null
}

/** Every wallet the picker can offer, available ones first within the featured / other order. */
export async function listWallets(): Promise<WalletOption[]> {
  const providers = [...(testProvider() ? [testProvider()!] : []), ...(await kitProviders())]
  const featured = (id: string) => {
    const i = FEATURED_WALLETS.indexOf(id)
    return i === -1 ? FEATURED_WALLETS.length : i
  }
  const options = await Promise.all(
    providers.map(async (p) => ({
      id: p.id,
      name: p.name,
      url: p.url,
      kind: p.id === TEST_WALLET_ID ? ('test' as const) : (CATALOG[p.id]?.kind ?? 'extension'),
      available: await p.isInstalled(),
    })),
  )
  return options
    .map((o, i) => ({ o, i }))
    .sort((a, b) => featured(a.o.id) - featured(b.o.id) || a.i - b.i)
    .map(({ o }) => o)
}

/** Install page of a wallet the kit knows (the kit's own product URL for non-featured modules). */
export async function walletInstallUrl(id: WalletId): Promise<string> {
  if (CATALOG[id]) return CATALOG[id]!.url
  const { kitModules } = await loadKit()
  return kitModules().find((m) => m.productId === id)?.productUrl ?? ''
}

/** The chosen wallet's id, if any (remembered across visits). */
export function selectedWalletId(): WalletId | null {
  return active?.provider.id ?? readChoice()?.id ?? null
}

/** Display name of the active wallet ("your wallet" before one is chosen). */
export function walletProviderName(): string {
  return active?.provider.name ?? 'your wallet'
}

/** How the active wallet proves ownership of an account. */
export function walletProof(): AccountProof {
  return active?.provider.proof ?? 'transaction'
}

/** The passkey wallet in use, when the chosen wallet is one. */
export function activePasskey(): PasskeyWalletRef | null {
  if (active?.provider.id !== PASSKEY_WALLET_ID) return null
  return readChoice()?.passkey ?? null
}

/** Whether the active wallet can sign SEP-53 messages. */
export function walletSignsMessages(): boolean {
  return !!active?.provider.signMessage && active.provider.id !== PASSKEY_WALLET_ID
}

/**
 * Chooses a wallet and asks it for access (a prompt in most wallets). Remembers the choice. For a passkey
 * wallet, pass the wallet BountyFlow verified for this account.
 */
export async function selectWallet(id: WalletId, passkey?: PasskeyWalletRef): Promise<string> {
  const provider = await providerFor(id, passkey)
  if (!provider) throw new WalletError('NOT_INSTALLED', 'This wallet is not available in this browser.')
  if (!(await provider.isInstalled())) {
    throw new WalletError('NOT_INSTALLED', `${provider.name} is not installed in this browser.`)
  }
  const address = await provider.requestAccess()
  active = { provider, address }
  writeChoice({ id, address, passkey })
  return address
}

/** Silently restores the remembered wallet (never prompts). Returns its address, or null. */
export async function restoreWallet(): Promise<string | null> {
  const choice = readChoice()
  if (choice) {
    const provider = await providerFor(choice.id, choice.passkey).catch(() => null)
    if (provider && (await provider.isInstalled())) {
      const address = (await provider.getAddress()) ?? choice.address
      active = { provider, address }
      return address
    }
    return null
  }
  if (testWalletAutoConnects()) {
    const provider = testProvider()!
    const address = await provider.getAddress()
    active = { provider, address }
    return address
  }
  return null
}

/** Forgets the chosen wallet in this browser (the wallet itself stays authorised). */
export function forgetWallet() {
  active = null
  writeChoice(null)
}

// ---------------------------------------------------------------------------
// Public API (stable for callers)
// ---------------------------------------------------------------------------

function requireActive(): WalletProvider {
  if (!active) throw new WalletError('NOT_CONNECTED', 'Choose a wallet first.')
  return active.provider
}

/** Is the chosen wallet installed (and reachable from this page)? */
export async function isWalletInstalled(): Promise<boolean> {
  return active ? active.provider.isInstalled() : false
}

/** @deprecated Kept for callers of the Freighter-only integration; checks the chosen wallet. */
export const isFreighterInstalled = isWalletInstalled

/** Asks the chosen wallet for access again (it may prompt). */
export async function connectWallet(): Promise<string> {
  const provider = requireActive()
  const address = await provider.requestAccess()
  active = { provider, address }
  const choice = readChoice()
  writeChoice({ id: provider.id, address, passkey: choice?.passkey })
  return address
}

/** Returns the current address without prompting; null when no wallet is chosen yet. */
export async function getWalletAddress(): Promise<string | null> {
  return active?.address ?? null
}

/** The chosen wallet's network; null when the wallet cannot report it. */
export async function getWalletNetwork(): Promise<WalletNetwork | null> {
  return requireActive().getNetwork()
}

/** Throws WRONG_NETWORK when the wallet reports a network other than the one the API expects. */
export async function assertWalletNetwork(expectedPassphrase: string): Promise<WalletNetwork | null> {
  const provider = requireActive()
  const net = await provider.getNetwork()
  if (net && net.networkPassphrase && net.networkPassphrase !== expectedPassphrase) {
    throw new WalletError(
      'WRONG_NETWORK',
      `${provider.name} is on ${net.network || 'another network'}. Switch it to the network shown in BountyFlow and try again.`,
      { expected: expectedPassphrase, actual: net.networkPassphrase },
    )
  }
  return net
}

export type SignOptions = { networkPassphrase: string; address: string }

/**
 * Signs a transaction XDR in the wallet after checking the network and the active account. Returns the signed
 * XDR (the API submits it). For a passkey wallet this signs the wallet's authorization entries.
 */
export async function signTransaction(
  xdr: string,
  { networkPassphrase, address }: SignOptions,
): Promise<string> {
  const provider = requireActive()
  await assertWalletNetwork(networkPassphrase)
  const { signedXdr, signer } = await provider.sign(xdr, { networkPassphrase, address })
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

/** SEP-53: signs a plain-text message with the account's key. Returns the base64 signature. */
export async function signMessage(
  message: string,
  { networkPassphrase, address }: SignOptions,
): Promise<string> {
  const provider = requireActive()
  if (!provider.signMessage) throw new WalletError('UNSUPPORTED', `${provider.name} cannot sign messages.`)
  const { signature, signer } = await provider.signMessage(message, { networkPassphrase, address })
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
  return signature
}

/** SEP-45: a passkey wallet authorizes its entry of a web-auth challenge (base64 `SorobanAuthorizationEntries`). */
export async function signContractChallenge(entriesXdr: string, passkey: PasskeyWalletRef): Promise<string> {
  try {
    const { signChallenge } = await loadPasskeyKit()
    return await signChallenge(
      {
        rpcUrl: passkey.rpcUrl,
        networkPassphrase: passkey.networkPassphrase,
        walletWasmHash: passkey.walletWasmHash,
      },
      entriesXdr,
      passkey.contractId,
      passkey.keyId,
    )
  } catch (e) {
    throw passkeyError(e)
  }
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
