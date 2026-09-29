import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { errorMessage, isApiError } from '@/lib/api/client'
import { transactionsApi } from '@/lib/api/endpoints'
import { invalidateAfterChainAction } from '@/lib/api/queries/chain'
import type { BlockchainTransaction, PreparedTransaction } from '@/lib/api/types'
import { useWalletStore } from '@/stores/wallet'

import { isWalletError, signTransaction } from './wallet'

export type ChainStep =
  'idle' | 'preparing' | 'awaiting_review' | 'signing' | 'submitting' | 'confirming' | 'confirmed' | 'failed'

export type ChainErrorKind =
  | 'user_rejected'
  | 'insufficient_balance'
  | 'network_mismatch'
  | 'expired'
  | 'contract_error'
  | 'wallet_not_installed'
  | 'wallet_required'
  | 'timeout'
  | 'api_error'
  | 'unknown'

export type ChainActionError = { kind: ChainErrorKind; message: string; detail?: string | null }

export type ChainActionState = {
  step: ChainStep
  prepared: PreparedTransaction | null
  transaction: BlockchainTransaction | null
  error: ChainActionError | null
}

export type UseChainActionOptions = {
  /** Calls the relevant `/prepare` endpoint. Receives the wallet address to act from. */
  prepare: (walletAddress: string) => Promise<PreparedTransaction>
  onConfirmed?: (tx: BlockchainTransaction) => void
  /**
   * While this returns true (e.g. the review dialog is open), refreshing the
   * affected queries is postponed until `flush()` — so the button that opened
   * the dialog is not unmounted by the page re-rendering mid-flow.
   */
  holdInvalidation?: () => boolean
  pollIntervalMs?: number
  timeoutMs?: number
}

const TERMINAL = new Set(['CONFIRMED', 'FAILED', 'EXPIRED'])

const INITIAL: ChainActionState = { step: 'idle', prepared: null, transaction: null, error: null }

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

function classifyText(text: string | null | undefined): ChainErrorKind | null {
  if (!text) return null
  const t = text.toLowerCase()
  if (/(insufficient|underfunded|not enough|balance too low|op_underfunded)/.test(t))
    return 'insufficient_balance'
  if (/(expired|too late|tx_too_late|timebounds)/.test(t)) return 'expired'
  if (/(network mismatch|wrong network|passphrase)/.test(t)) return 'network_mismatch'
  if (/(reject|declin|denied)/.test(t)) return 'user_rejected'
  return null
}

const KIND_MESSAGES: Record<ChainErrorKind, string> = {
  user_rejected: 'You rejected the request in your wallet. Nothing was submitted.',
  insufficient_balance: 'The wallet does not have enough funds to cover this amount plus network fees.',
  network_mismatch:
    'Your wallet is on a different Stellar network than BountyFlow. Switch networks and retry.',
  expired: 'This prepared transaction expired before it was submitted. Start again to get a fresh one.',
  contract_error: 'The escrow contract rejected this transaction.',
  wallet_not_installed: 'This wallet is not installed in this browser. Choose another one to sign with.',
  wallet_required: 'Connect a Stellar wallet to continue.',
  timeout: 'The network has not confirmed the transaction yet. It may still settle; check back shortly.',
  api_error: 'The BountyFlow API could not complete this step.',
  unknown: 'Something went wrong while processing the transaction.',
}

/** Maps wallet, API, and on-chain failures onto a small, user-facing set. */
export function mapChainError(e: unknown): ChainActionError {
  if (isWalletError(e)) {
    const kind: ChainErrorKind =
      e.code === 'USER_REJECTED'
        ? 'user_rejected'
        : e.code === 'WRONG_NETWORK'
          ? 'network_mismatch'
          : e.code === 'NOT_INSTALLED'
            ? 'wallet_not_installed'
            : 'unknown'
    return { kind, message: kind === 'unknown' ? e.message : KIND_MESSAGES[kind], detail: e.message }
  }
  if (isApiError(e)) {
    const requestDetail = e.requestId ? `Request ID ${e.requestId}` : null
    // Structured codes first: they are more reliable than matching on message text.
    if (e.code === 'contract_rejected') {
      return {
        kind: 'contract_error',
        message: errorMessage(e),
        detail: e.contractError ? `Contract error: ${e.contractError}` : requestDetail,
      }
    }
    // Asset guards name the asset and the wallet; their message is the one to show.
    if (
      e.code === 'trustline_missing' ||
      e.code === 'trustline_unauthorized' ||
      e.code === 'insufficient_balance' ||
      e.code === 'asset_not_supported'
    ) {
      return {
        kind: e.code === 'insufficient_balance' ? 'insufficient_balance' : 'api_error',
        message: e.message,
        detail: requestDetail,
      }
    }
    if (e.code === 'wallet_not_verified' || e.code === 'wrong_wallet') {
      return { kind: 'wallet_required', message: errorMessage(e), detail: requestDetail }
    }
    if (
      e.code === 'account_not_found' ||
      e.code === 'signature_invalid' ||
      e.code === 'escrow_unverified' ||
      e.code === 'service_unavailable' ||
      e.code === 'rate_limited' ||
      e.code === 'network_error'
    ) {
      return { kind: 'api_error', message: errorMessage(e), detail: requestDetail }
    }
    const fromText = classifyText(e.message)
    if (fromText) return { kind: fromText, message: KIND_MESSAGES[fromText], detail: e.message }
    if (e.code === 'blockchain_error')
      return { kind: 'contract_error', message: KIND_MESSAGES.contract_error, detail: e.message }
    return { kind: 'api_error', message: e.message || KIND_MESSAGES.api_error, detail: requestDetail }
  }
  if (e instanceof Error) {
    const fromText = classifyText(e.message)
    if (fromText) return { kind: fromText, message: KIND_MESSAGES[fromText], detail: e.message }
    return { kind: 'unknown', message: e.message || KIND_MESSAGES.unknown }
  }
  return { kind: 'unknown', message: KIND_MESSAGES.unknown }
}

function errorFromTransaction(tx: BlockchainTransaction): ChainActionError {
  if (tx.status === 'EXPIRED')
    return { kind: 'expired', message: KIND_MESSAGES.expired, detail: tx.failure_reason }
  const kind = classifyText(tx.failure_reason) ?? 'contract_error'
  return { kind, message: KIND_MESSAGES[kind], detail: tx.failure_reason }
}

/**
 * Drives every on-chain action through the same flow:
 * prepare → review → sign in the wallet →
 * POST /transactions/{id}/submit → poll GET /transactions/{id} (2s, 90s max)
 * → invalidate affected queries.
 */
export function useChainAction(options: UseChainActionOptions) {
  const { pollIntervalMs = 2000, timeoutMs = 90_000 } = options
  const client = useQueryClient()
  const [state, setState] = useState<ChainActionState>(INITIAL)
  const runId = useRef(0)
  /** Guards confirm() against double clicks landing in the same render. */
  const confirmingRun = useRef<number | null>(null)
  const optionsRef = useRef(options)

  useEffect(() => {
    optionsRef.current = options
  })

  /** Bounty whose queries still need a refresh (see `holdInvalidation`). */
  const pendingInvalidation = useRef<{ bountyId: string | null } | null>(null)

  const invalidate = useCallback(
    (bountyId: string | null) => {
      if (optionsRef.current.holdInvalidation?.()) {
        pendingInvalidation.current = { bountyId }
        return
      }
      invalidateAfterChainAction(client, bountyId)
    },
    [client],
  )

  /** Runs a postponed invalidation, if any. */
  const flush = useCallback(() => {
    const pending = pendingInvalidation.current
    pendingInvalidation.current = null
    if (pending) invalidateAfterChainAction(client, pending.bountyId)
  }, [client])

  useEffect(
    () => () => {
      // Invalidate any in-flight run on unmount, and never drop a pending refresh.
      runId.current += 1
      const pending = pendingInvalidation.current
      pendingInvalidation.current = null
      if (pending) invalidateAfterChainAction(client, pending.bountyId)
    },
    [client],
  )

  const fail = useCallback((id: number, error: ChainActionError, patch: Partial<ChainActionState> = {}) => {
    if (runId.current !== id) return
    setState((s) => ({ ...s, ...patch, step: 'failed', error }))
  }, [])

  /** Step 1: resolve a wallet address and call the prepare endpoint. */
  const start = useCallback(async () => {
    const id = ++runId.current
    const opts = optionsRef.current
    setState({ ...INITIAL, step: 'preparing' })

    const wallet = useWalletStore.getState()
    let address: string | null = wallet.address
    if (!address) {
      address = await wallet.connect()
      if (runId.current !== id) return
      if (!address) {
        const status = useWalletStore.getState().status
        fail(id, {
          kind: status === 'not_installed' ? 'wallet_not_installed' : 'wallet_required',
          message:
            status === 'not_installed' ? KIND_MESSAGES.wallet_not_installed : KIND_MESSAGES.wallet_required,
          detail: useWalletStore.getState().error,
        })
        return
      }
    }

    try {
      const prepared = await opts.prepare(address)
      if (runId.current !== id) return
      setState({ step: 'awaiting_review', prepared, transaction: prepared.transaction, error: null })
    } catch (e) {
      fail(id, mapChainError(e))
    }
  }, [fail])

  const poll = useCallback(
    async (id: number, tx: BlockchainTransaction) => {
      const deadline = Date.now() + timeoutMs
      let current = tx
      while (!TERMINAL.has(current.status)) {
        if (Date.now() >= deadline) {
          fail(id, { kind: 'timeout', message: KIND_MESSAGES.timeout }, { transaction: current })
          invalidate(current.bounty_id)
          return
        }
        await sleep(pollIntervalMs)
        if (runId.current !== id) return
        try {
          current = await transactionsApi.get(current.id)
        } catch (e) {
          // Transient read errors: keep polling until the deadline.
          if (isApiError(e) && (e.status === 404 || e.status === 403)) {
            fail(id, mapChainError(e), { transaction: current })
            return
          }
          continue
        }
        if (runId.current !== id) return
        setState((s) => ({ ...s, transaction: current }))
      }

      invalidate(current.bounty_id)
      if (current.status === 'CONFIRMED') {
        setState((s) => ({ ...s, step: 'confirmed', transaction: current, error: null }))
        optionsRef.current.onConfirmed?.(current)
      } else {
        fail(id, errorFromTransaction(current), { transaction: current })
      }
    },
    [fail, invalidate, pollIntervalMs, timeoutMs],
  )

  /** Step 2: user confirmed the review → sign in the wallet → submit → poll. */
  const confirm = useCallback(async () => {
    const id = runId.current
    const prepared = state.prepared
    if (!prepared || state.step !== 'awaiting_review') return
    if (confirmingRun.current === id) return
    confirmingRun.current = id

    if (new Date(prepared.expires_at).getTime() <= Date.now()) {
      fail(id, { kind: 'expired', message: KIND_MESSAGES.expired })
      return
    }

    if (!prepared.unsigned_xdr) {
      fail(id, { kind: 'api_error', message: 'The API did not return a transaction to sign.' })
      return
    }
    const address = prepared.transaction.source_address ?? useWalletStore.getState().address
    if (!address) {
      fail(id, { kind: 'wallet_required', message: KIND_MESSAGES.wallet_required })
      return
    }
    setState((s) => ({ ...s, step: 'signing' }))
    let signedXdr: string
    try {
      signedXdr = await signTransaction(prepared.unsigned_xdr, {
        networkPassphrase: prepared.network_passphrase,
        address,
      })
    } catch (e) {
      fail(id, mapChainError(e))
      return
    }
    if (runId.current !== id) return

    setState((s) => ({ ...s, step: 'submitting' }))
    let submitted: BlockchainTransaction
    try {
      submitted = await transactionsApi.submit(prepared.transaction.id, { signed_xdr: signedXdr })
    } catch (e) {
      fail(id, mapChainError(e))
      invalidate(prepared.transaction.bounty_id)
      return
    }
    if (runId.current !== id) return
    setState((s) => ({ ...s, step: 'confirming', transaction: submitted }))
    await poll(id, submitted)
  }, [fail, invalidate, poll, state.prepared, state.step])

  const reset = useCallback(() => {
    runId.current += 1
    setState(INITIAL)
  }, [])

  const isBusy = ['preparing', 'signing', 'submitting', 'confirming'].includes(state.step)

  return { ...state, isBusy, start, confirm, reset, flush }
}

export type ChainActionController = ReturnType<typeof useChainAction>
