import { create } from 'zustand'

import {
  forgetWallet,
  getWalletNetwork,
  restoreWallet,
  selectedWalletId,
  selectWallet,
  walletErrorMessage,
  walletProviderName,
  type PasskeyWalletRef,
  type WalletId,
  type WalletNetwork,
} from '@/lib/stellar/wallet'

async function readNetwork(): Promise<WalletNetwork | null> {
  try {
    return await getWalletNetwork()
  } catch {
    return null
  }
}

export type WalletStatus = 'unknown' | 'not_installed' | 'disconnected' | 'connecting' | 'connected' | 'error'

type WalletState = {
  status: WalletStatus
  /** The chosen wallet app (kit product id, "passkey" or the E2E test wallet). */
  walletId: WalletId | null
  walletName: string | null
  address: string | null
  network: WalletNetwork | null
  error: string | null
  /** The wallet picker dialog (rendered once, by `WalletPickerHost`). */
  pickerOpen: boolean
  /** The wallet being connected from the picker. */
  choosing: WalletId | null
  /** Silent restore of the remembered wallet on app start: never prompts the user. */
  detect: () => Promise<void>
  /**
   * Resolves an address to act from: opens the wallet picker and waits for the user's choice. Resolves null
   * when the picker is closed without connecting.
   */
  connect: () => Promise<string | null>
  /** From the picker: choose a wallet and ask it for access. */
  choose: (id: WalletId, passkey?: PasskeyWalletRef) => Promise<string | null>
  openPicker: () => void
  closePicker: () => void
  /** Re-reads the active network (after the user switches it in the wallet). */
  refreshNetwork: () => Promise<void>
  /** Forget the wallet in this browser (the wallet itself stays authorised). */
  disconnect: () => void
}

let pending: ((address: string | null) => void) | null = null

function settle(address: string | null) {
  const resolve = pending
  pending = null
  resolve?.(address)
}

export const useWalletStore = create<WalletState>()((set, get) => ({
  status: 'unknown',
  walletId: null,
  walletName: null,
  address: null,
  network: null,
  error: null,
  pickerOpen: false,
  choosing: null,

  detect: async () => {
    const address = await restoreWallet().catch(() => null)
    if (!address) {
      set({ status: 'disconnected', address: null, walletId: null, walletName: null })
      return
    }
    const network = await readNetwork()
    set({
      status: 'connected',
      address,
      network,
      error: null,
      walletId: selectedWalletId(),
      walletName: walletProviderName(),
    })
  },

  connect: () => {
    settle(null) // a previous, abandoned request
    set({ pickerOpen: true, error: null })
    return new Promise<string | null>((resolve) => {
      pending = resolve
    })
  },

  choose: async (id, passkey) => {
    set({ status: 'connecting', error: null, choosing: id })
    try {
      const address = await selectWallet(id, passkey)
      const network = await readNetwork()
      set({
        status: 'connected',
        address,
        network,
        error: null,
        walletId: id,
        walletName: walletProviderName(),
        pickerOpen: false,
        choosing: null,
      })
      settle(address)
      return address
    } catch (e) {
      set({ status: get().address ? 'connected' : 'error', error: walletErrorMessage(e), choosing: null })
      return null
    }
  },

  openPicker: () => set({ pickerOpen: true, error: null }),

  closePicker: () => {
    set({ pickerOpen: false })
    settle(null)
  },

  refreshNetwork: async () => {
    set({ network: await readNetwork() })
  },

  disconnect: () => {
    forgetWallet()
    set({
      status: 'disconnected',
      address: null,
      network: null,
      error: null,
      walletId: null,
      walletName: null,
    })
  },
}))
