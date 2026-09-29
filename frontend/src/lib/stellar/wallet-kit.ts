/**
 * Stellar Wallets Kit modules (lazy chunk).
 *
 * `wallet.ts` imports this file with a dynamic `import()`, so the kit and every
 * wallet SDK it bundles (Freighter, xBull, Albedo, LOBSTR, Hana and the other
 * modules that need no API keys) load only when a wallet is actually used.
 * BountyFlow draws its own wallet picker, so the kit's modal UI is not used:
 * only its per-wallet modules, which all speak the same `ModuleInterface`.
 */
import type { ModuleInterface } from '@creit.tech/stellar-wallets-kit/types'
import { defaultModules } from '@creit.tech/stellar-wallets-kit/modules/utils'

export type { ModuleInterface }

let modules: ModuleInterface[] | null = null

/** Every kit module that works without extra configuration (WalletConnect, Ledger and Trezor need some). */
export function kitModules(): ModuleInterface[] {
  modules ??= defaultModules()
  return modules
}
