import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { errorMessage } from '@/lib/api/client'
import { walletsApi } from '@/lib/api/endpoints'
import { invalidateWallets } from '@/lib/api/queries/wallets'
import type { Wallet } from '@/lib/api/types'
import {
  activePasskey,
  isWalletError,
  signContractChallenge,
  signMessage,
  signTransaction,
  walletErrorMessage,
  walletProof,
  walletSignsMessages,
  type PasskeyWalletRef,
} from '@/lib/stellar/wallet'
import { useWalletStore } from '@/stores/wallet'

async function proveAccount(address: string, walletApp: string | undefined): Promise<Wallet> {
  const useMessage = walletProof() === 'message'
  if (!useMessage) {
    const challenge = await walletsApi.challenge({ public_address: address, method: 'sep10' })
    try {
      const signed = await signTransaction(challenge.challenge_xdr ?? '', {
        networkPassphrase: challenge.network_passphrase,
        address,
      })
      return await walletsApi.verify({
        public_address: address,
        signed_challenge_xdr: signed,
        wallet_app: walletApp,
      })
    } catch (e) {
      // A wallet that cannot sign the challenge transaction may still sign a message (SEP-53).
      if (!(isWalletError(e) && e.code === 'UNSUPPORTED' && walletSignsMessages())) throw e
    }
  }
  const challenge = await walletsApi.challenge({ public_address: address, method: 'sep53' })
  const signature = await signMessage(challenge.message ?? '', {
    networkPassphrase: challenge.network_passphrase,
    address,
  })
  return walletsApi.verify({ public_address: address, signed_message: signature, wallet_app: walletApp })
}

async function proveContract(passkey: PasskeyWalletRef): Promise<Wallet> {
  const address = passkey.contractId
  const challenge = await walletsApi.challenge({ public_address: address, method: 'sep45' })
  const signed = await signContractChallenge(challenge.authorization_entries ?? '', passkey)
  return walletsApi.verify({
    public_address: address,
    signed_authorization_entries: signed,
    wallet_app: 'passkey',
  })
}

/**
 * Proves wallet ownership without submitting anything: a SEP-10 challenge transaction or a SEP-53 message for
 * account wallets, a SEP-45 authorization for passkey smart wallets (checked by simulation on the network).
 */
export function useVerifyOwnership() {
  const client = useQueryClient()
  const [pending, setPending] = useState(false)
  const verify = async (address: string, passkey?: PasskeyWalletRef | null) => {
    if (pending) return false
    setPending(true)
    try {
      const contract = passkey ?? (address.startsWith('C') ? activePasskey() : null)
      if (contract) await proveContract(contract)
      else await proveAccount(address, useWalletStore.getState().walletId ?? undefined)
      toast.success('Wallet ownership verified by signature')
      await invalidateWallets(client)
      return true
    } catch (e) {
      toast.error(isWalletError(e) ? walletErrorMessage(e) : errorMessage(e))
      return false
    } finally {
      setPending(false)
    }
  }
  return { verify, pending }
}
