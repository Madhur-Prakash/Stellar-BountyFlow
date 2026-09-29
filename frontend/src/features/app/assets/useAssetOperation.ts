import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { errorMessage } from '@/lib/api/client'
import { assetsApi } from '@/lib/api/endpoints'
import { invalidateAfterAssetOperation } from '@/lib/api/queries/assets'
import type { AssetOperation, PreparedAssetOperation } from '@/lib/api/types'
import { isWalletError, signTransaction, walletErrorMessage } from '@/lib/stellar/wallet'

export type AssetOpStep =
  'idle' | 'preparing' | 'review' | 'signing' | 'submitting' | 'confirming' | 'confirmed' | 'failed'

export type AssetOpState = {
  step: AssetOpStep
  prepared: PreparedAssetOperation | null
  operation: AssetOperation | null
  error: string | null
}

const INITIAL: AssetOpState = { step: 'idle', prepared: null, operation: null, error: null }
const TERMINAL = new Set(['CONFIRMED', 'FAILED', 'EXPIRED'])
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/**
 * Drives a wallet-signed asset operation (adding a trustline, deploying an asset contract): the API builds the
 * transaction from a verified wallet, the wallet signs it, the API submits it and confirms it only once the
 * effect is visible on the network.
 */
export function useAssetOperation({
  prepare,
  onConfirmed,
  pollIntervalMs = 2000,
  timeoutMs = 90_000,
}: {
  prepare: () => Promise<PreparedAssetOperation>
  onConfirmed?: (op: AssetOperation) => void
  pollIntervalMs?: number
  timeoutMs?: number
}) {
  const client = useQueryClient()
  const [state, setState] = useState<AssetOpState>(INITIAL)
  const run = useRef(0)
  const options = useRef({ prepare, onConfirmed })
  useEffect(() => {
    options.current = { prepare, onConfirmed }
  })
  useEffect(
    () => () => {
      run.current += 1
    },
    [],
  )

  const fail = useCallback((id: number, error: string) => {
    if (run.current === id) setState((s) => ({ ...s, step: 'failed', error }))
  }, [])

  const start = useCallback(async () => {
    const id = ++run.current
    setState({ ...INITIAL, step: 'preparing' })
    try {
      const prepared = await options.current.prepare()
      if (run.current !== id) return
      setState({ step: 'review', prepared, operation: prepared.operation, error: null })
    } catch (e) {
      fail(id, errorMessage(e))
    }
  }, [fail])

  const confirm = useCallback(async () => {
    const id = run.current
    const prepared = state.prepared
    if (!prepared || state.step !== 'review') return
    if (new Date(prepared.expires_at).getTime() <= Date.now()) {
      fail(id, 'This transaction expired before it was signed. Start again.')
      return
    }
    setState((s) => ({ ...s, step: 'signing' }))
    let signed: string
    try {
      signed = await signTransaction(prepared.unsigned_xdr, {
        networkPassphrase: prepared.network_passphrase,
        address: prepared.operation.source_address,
      })
    } catch (e) {
      fail(id, isWalletError(e) ? walletErrorMessage(e) : errorMessage(e))
      return
    }
    if (run.current !== id) return
    setState((s) => ({ ...s, step: 'submitting' }))
    let op: AssetOperation
    try {
      op = await assetsApi.submitOperation(prepared.operation.id, signed)
    } catch (e) {
      fail(id, errorMessage(e))
      return
    }
    const deadline = Date.now() + timeoutMs
    setState((s) => ({ ...s, step: 'confirming', operation: op }))
    while (!TERMINAL.has(op.status)) {
      if (Date.now() >= deadline) {
        fail(id, 'The network has not confirmed this yet. It may still settle; check back shortly.')
        return
      }
      await sleep(pollIntervalMs)
      if (run.current !== id) return
      try {
        op = await assetsApi.getOperation(op.id)
      } catch {
        continue
      }
      setState((s) => ({ ...s, operation: op }))
    }
    invalidateAfterAssetOperation(client)
    if (op.status === 'CONFIRMED') {
      setState((s) => ({ ...s, step: 'confirmed', operation: op, error: null }))
      options.current.onConfirmed?.(op)
    } else {
      fail(id, op.failure_reason ?? 'The transaction did not complete.')
    }
  }, [client, fail, pollIntervalMs, state.prepared, state.step, timeoutMs])

  const reset = useCallback(() => {
    run.current += 1
    setState(INITIAL)
  }, [])

  const busy = ['preparing', 'signing', 'submitting', 'confirming'].includes(state.step)
  return { ...state, busy, start, confirm, reset }
}

export type AssetOperationController = ReturnType<typeof useAssetOperation>
