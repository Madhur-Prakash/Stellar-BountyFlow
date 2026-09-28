import { create } from 'zustand'

import {
  connectWallet,
  getWalletAddress,
  getWalletNetwork,
  isFreighterInstalled,
  walletErrorMessage,
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
  address: string | null
  network: WalletNetwork | null
  error: string | null
  /** Silent detection on app start: never prompts the user. */
  detect: () => Promise<void>
  /** Prompts Freighter for access. */
  connect: () => Promise<string | null>
  /** Re-reads the active network (after the user switches in Freighter). */
  refreshNetwork: () => Promise<void>
  /** Forget the address locally (Freighter itself stays authorised). */
  disconnect: () => void
}

export const useWalletStore = create<WalletState>()((set) => ({
  status: 'unknown',
  address: null,
  network: null,
  error: null,

  detect: async () => {
    const installed = await isFreighterInstalled()
    if (!installed) {
      set({ status: 'not_installed', address: null, network: null })
      return
    }
    const address = await getWalletAddress()
    if (!address) {
      set({ status: 'disconnected', address: null })
      return
    }
    const network = await readNetwork()
    set({ status: 'connected', address, network, error: null })
  },

  connect: async () => {
    set({ status: 'connecting', error: null })
    try {
      const address = await connectWallet()
      const network = await readNetwork()
      set({ status: 'connected', address, network, error: null })
      return address
    } catch (e) {
      const installed = await isFreighterInstalled()
      set({
        status: installed ? 'error' : 'not_installed',
        error: walletErrorMessage(e),
        address: null,
      })
      return null
    }
  },

  refreshNetwork: async () => {
    set({ network: await readNetwork() })
  },

  disconnect: () => set({ status: 'disconnected', address: null, network: null, error: null }),
}))
