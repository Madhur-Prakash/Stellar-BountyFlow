import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import type { Me } from '../types'
import { clearPrivateCache } from './auth'
import { qk } from './keys'

describe('clearPrivateCache', () => {
  it('never orphans an in-flight `me` query (regression: stuck "Checking your session…")', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let resolveMe: (v: Me | null) => void = () => {}
    const observer = new QueryObserver(client, {
      queryKey: qk.auth.me,
      queryFn: () => new Promise<Me | null>((r) => (resolveMe = r)),
    })
    const seen: string[] = []
    const unsubscribe = observer.subscribe((r) => seen.push(r.status))

    // A failed refresh inside the me-query's queryFn triggers the auth-failure handler mid-fetch.
    clearPrivateCache(client)
    resolveMe(null)
    await new Promise((r) => setTimeout(r, 0))

    const result = observer.getCurrentResult()
    expect(result.status).toBe('success')
    expect(result.data).toBeNull()
    expect(client.getQueryCache().find({ queryKey: qk.auth.me })).toBeDefined()
    unsubscribe()
  })

  it('drops other private data but keeps public caches', () => {
    const client = new QueryClient()
    client.setQueryData(qk.payments.mine({}), { items: [] })
    client.setQueryData(qk.wallets.all, [])
    client.setQueryData(qk.config, { app_name: 'x' })
    clearPrivateCache(client)
    expect(client.getQueryData(qk.payments.mine({}))).toBeUndefined()
    expect(client.getQueryData(qk.wallets.all)).toBeUndefined()
    expect(client.getQueryData(qk.config)).toEqual({ app_name: 'x' })
    expect(client.getQueryData(qk.auth.me)).toBeNull()
  })
})
