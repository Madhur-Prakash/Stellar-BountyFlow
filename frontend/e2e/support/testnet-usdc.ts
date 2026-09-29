import { Account, Asset, Operation, TransactionBuilder } from '@stellar/stellar-sdk'
import type { Keypair } from '@stellar/stellar-sdk'

import { expect } from '../fixtures'

import { TESTNET_PASSPHRASE } from './wallet'

/**
 * Real Testnet USDC for a throwaway keypair.
 *
 * Circle's faucet (https://faucet.circle.com) hands out Testnet USDC to a wallet a person owns, which a headless
 * test cannot drive. The Testnet SDF order book carries the same asset, so the suite buys it: a
 * `pathPaymentStrictSend` that sends XLM from the account to itself and receives USDC. Nothing is mocked — the
 * account really holds USDC afterwards, and the escrow really moves it.
 *
 * The account must already have a USDC trustline (the spec adds it through the product's own UI).
 */

export const USDC_CODE = 'USDC'
export const USDC_ISSUER = 'GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5'
export const USDC = new Asset(USDC_CODE, USDC_ISSUER)
export const USDC_IDENTIFIER = `${USDC_CODE}:${USDC_ISSUER}`

const HORIZON = process.env.E2E_HORIZON_URL ?? 'https://horizon-testnet.stellar.org'

type HorizonBalance = {
  asset_type: string
  asset_code?: string
  asset_issuer?: string
  balance: string
}

async function account(address: string): Promise<{ sequence: string; balances: HorizonBalance[] }> {
  const res = await fetch(`${HORIZON}/accounts/${address}`)
  if (!res.ok) throw new Error(`Horizon could not load ${address}: HTTP ${res.status}`)
  return (await res.json()) as { sequence: string; balances: HorizonBalance[] }
}

/** The account's USDC balance, or "0" when it has no trustline yet. */
export async function usdcBalance(address: string): Promise<string> {
  const { balances } = await account(address)
  const row = balances.find((b) => b.asset_code === USDC_CODE && b.asset_issuer === USDC_ISSUER)
  return row?.balance ?? '0'
}

export async function hasUsdcTrustline(address: string): Promise<boolean> {
  const { balances } = await account(address)
  return balances.some((b) => b.asset_code === USDC_CODE && b.asset_issuer === USDC_ISSUER)
}

async function submit(xdr: string): Promise<void> {
  const res = await fetch(`${HORIZON}/transactions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ tx: xdr }),
  })
  const body = (await res.json()) as { successful?: boolean; extras?: { result_codes?: unknown } }
  if (!res.ok || body.successful === false) {
    throw new Error(`Horizon rejected the transaction: ${JSON.stringify(body.extras?.result_codes ?? body)}`)
  }
}

/**
 * Buys at least `minimumUsdc` USDC for XLM on the Testnet order book, paying the account itself.
 * `sendMax` caps how much XLM may be spent.
 */
export async function buyUsdc(
  keypair: Keypair,
  { minimumUsdc = '30', sendMax = '200' }: { minimumUsdc?: string; sendMax?: string } = {},
): Promise<string> {
  const address = keypair.publicKey()
  const { sequence } = await account(address)
  const tx = new TransactionBuilder(new Account(address, sequence), {
    fee: '10000',
    networkPassphrase: TESTNET_PASSPHRASE,
  })
    .addOperation(
      Operation.pathPaymentStrictSend({
        sendAsset: Asset.native(),
        sendAmount: sendMax,
        destination: address,
        destAsset: USDC,
        destMin: minimumUsdc,
        path: [],
      }),
    )
    .setTimeout(120)
    .build()
  tx.sign(keypair)
  await submit(tx.toXDR())
  const balance = await usdcBalance(address)
  expect(Number(balance), `bought at least ${minimumUsdc} USDC for ${address}`).toBeGreaterThanOrEqual(
    Number(minimumUsdc),
  )
  return balance
}
