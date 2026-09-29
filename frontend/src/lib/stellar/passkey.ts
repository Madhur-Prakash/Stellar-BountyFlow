/**
 * Passkey smart wallets (lazy chunk, loaded by `wallet.ts` and the passkey wallet card).
 *
 * passkey-kit registers a WebAuthn passkey (secp256r1) and authorizes the deployment of its smart-wallet
 * contract with that passkey as the only signer. BountyFlow's sponsor submits the deployment and pays for it;
 * the browser never needs XLM. Afterwards the wallet signs **Soroban authorization entries** (never whole
 * transactions): the API prepares every call with the sponsor as the transaction source, the passkey signs the
 * wallet's entries here, and the API relays them (see backend `app/blockchain/sponsorship.py`).
 */
import './buffer-polyfill'

import { Address, TransactionBuilder, xdr } from '@stellar/stellar-sdk'
import { PasskeyClient, PasskeyKit, PasskeySigner, type CreateWalletResult } from 'passkey-kit'
import { IndexedDBStorage } from 'passkey-kit/storage'

export type PasskeyConfig = {
  rpcUrl: string
  networkPassphrase: string
  walletWasmHash: string
}

let kit: PasskeyKit | null = null
let kitKey = ''

function getKit(config: PasskeyConfig): PasskeyKit {
  const key = `${config.rpcUrl}|${config.networkPassphrase}|${config.walletWasmHash}`
  if (!kit || kitKey !== key) {
    kit = new PasskeyKit({
      rpcUrl: config.rpcUrl,
      networkPassphrase: config.networkPassphrase,
      walletWasmHash: config.walletWasmHash,
      // The API prepares transactions with a 5 minute timeout; signatures must stay valid while it relays them.
      timeoutInSeconds: 120,
      storage: new IndexedDBStorage(),
    })
    kitKey = key
  }
  return kit
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

export type CreatedPasskeyWallet = {
  keyId: string
  publicKey: string
  contractId: string
  deployXdr: string
  /** Kept to confirm the deployment once the network has it (stores the verified wallet birth locally). */
  created: CreateWalletResult
}

/** Registers a passkey and authorizes the deployment of its wallet (one or two passkey prompts). */
export async function createPasskeyWallet(
  config: PasskeyConfig,
  userName: string,
): Promise<CreatedPasskeyWallet> {
  const created = await getKit(config).createWallet('BountyFlow', userName)
  return {
    keyId: created.keyIdBase64,
    publicKey: toHex(created.publicKey),
    contractId: created.contractId,
    deployXdr: created.signedTx,
    created,
  }
}

/** Verifies the deployment on-chain (passkey-kit reads it back from RPC) and remembers the wallet locally. */
export async function confirmPasskeyWallet(
  config: PasskeyConfig,
  created: CreateWalletResult,
  transactionHash: string,
): Promise<void> {
  const k = getKit(config)
  await k.confirmWalletCreation(created, transactionHash)
  attach(k, config, created.contractId, created.keyIdBase64)
}

/** Points the kit at a wallet BountyFlow has verified for this account (SEP-45), without another ceremony. */
function attach(k: PasskeyKit, config: PasskeyConfig, contractId: string, keyId: string) {
  if (k.wallet?.options.contractId === contractId && k.keyId === keyId) return
  k.wallet = new PasskeyClient({
    contractId,
    rpcUrl: config.rpcUrl,
    networkPassphrase: config.networkPassphrase,
  })
  k.keyId = keyId
}

function credentialAddress(entry: xdr.SorobanAuthorizationEntry): string | null {
  const credentials = entry.credentials()
  const name = credentials.switch().name
  if (name === 'sorobanCredentialsAddress')
    return Address.fromScAddress(credentials.address().address()).toString()
  if (name === 'sorobanCredentialsAddressV2')
    return Address.fromScAddress(credentials.addressV2().address()).toString()
  return null
}

async function signEntries(
  config: PasskeyConfig,
  entries: xdr.SorobanAuthorizationEntry[],
  contractId: string,
  keyId: string,
): Promise<{ entries: xdr.SorobanAuthorizationEntry[]; signed: number }> {
  const k = getKit(config)
  attach(k, config, contractId, keyId)
  const out: xdr.SorobanAuthorizationEntry[] = []
  let signed = 0
  for (const entry of entries) {
    if (credentialAddress(entry) === contractId) {
      out.push(await k.signAuthEntry(entry, new PasskeySigner(keyId)))
      signed += 1
    } else {
      out.push(entry)
    }
  }
  return { entries: out, signed }
}

/**
 * Signs the smart wallet's authorization entries of a prepared transaction and returns the transaction XDR with
 * them signed. The envelope itself is left unsigned: the API rebuilds it with the sponsor as the source.
 */
export async function signTransactionAuth(
  config: PasskeyConfig,
  transactionXdr: string,
  contractId: string,
  keyId: string,
): Promise<string> {
  // Parse first: only invokeHostFunction transactions carry authorization entries.
  TransactionBuilder.fromXDR(transactionXdr, config.networkPassphrase)
  const envelope = xdr.TransactionEnvelope.fromXDR(transactionXdr, 'base64')
  const operations = envelope.v1().tx().operations()
  if (operations.length !== 1 || operations[0]!.body().switch().name !== 'invokeHostFunction') {
    throw new Error('This transaction has nothing for the passkey wallet to sign.')
  }
  const op = operations[0]!.body().invokeHostFunctionOp()
  const { entries, signed } = await signEntries(config, op.auth(), contractId, keyId)
  if (signed === 0) throw new Error('This transaction does not need the passkey wallet’s authorization.')
  op.auth(entries)
  return envelope.toXDR('base64')
}

/** Signs the wallet's entry of a SEP-45 challenge (`SorobanAuthorizationEntries`, base64). */
export async function signChallenge(
  config: PasskeyConfig,
  entriesXdr: string,
  contractId: string,
  keyId: string,
): Promise<string> {
  const challenge = xdr.SorobanAuthorizationEntries.fromXDR(entriesXdr, 'base64')
  const { entries, signed } = await signEntries(config, challenge, contractId, keyId)
  if (signed === 0) throw new Error('The challenge was not issued for this wallet.')
  return xdr.SorobanAuthorizationEntries.toXDR(entries).toString('base64')
}
