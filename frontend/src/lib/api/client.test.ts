import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse } from '@/test/fixtures'

import { ApiError, apiRequest, buildQuery, errorMessage, http, setAuthFailureHandler } from './client'

type FetchCall = [string, RequestInit]

const fetchMock = vi.fn<(input: string, init: RequestInit) => Promise<Response>>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  setAuthFailureHandler(null)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const headersOf = (call: FetchCall) => call[1].headers as Record<string, string>

describe('CSRF double-submit', () => {
  it('sends X-CSRF-Token from the bf_csrf cookie on mutating requests', async () => {
    document.cookie = 'bf_csrf=tok%3D123; path=/'
    fetchMock.mockImplementation(async () => jsonResponse({ ok: true }))

    await http.post('/bounties/b1/bookmark')
    await http.patch('/users/me', { bio: 'hi' })
    await http.delete('/wallets/w1')

    for (const call of fetchMock.mock.calls as FetchCall[]) {
      expect(headersOf(call)['X-CSRF-Token']).toBe('tok=123')
      expect(call[1].credentials).toBe('include')
    }
  })

  it('does not send the CSRF header on GET requests', async () => {
    document.cookie = 'bf_csrf=abc; path=/'
    fetchMock.mockImplementation(async () => jsonResponse({ ok: true }))
    await http.get('/bounties', { q: 'rust' })
    const [url, init] = fetchMock.mock.calls[0] as FetchCall
    expect(url).toBe('/api/v1/bounties?q=rust')
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined()
    expect(init.credentials).toBe('include')
  })

  it('serialises JSON bodies', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'x' }, { status: 201 }))
    const res = await http.post<{ id: string }>('/bounties', { title: 'T' })
    const [, init] = fetchMock.mock.calls[0] as FetchCall
    expect(init.body).toBe('{"title":"T"}')
    expect(headersOf(fetchMock.mock.calls[0] as FetchCall)['Content-Type']).toBe('application/json')
    expect(res).toEqual({ id: 'x' })
  })
})

describe('error envelope parsing', () => {
  it('builds a typed ApiError with field errors', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'validation_error',
            message: 'Invalid input',
            details: [
              { field: 'title', message: 'Too short' },
              { field: 'reward_amount', message: 'Must be positive' },
            ],
            request_id: 'req_42',
          },
        },
        { status: 422 },
      ),
    )
    const err = await http.post('/bounties', {}).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiErr = err as ApiError
    expect(apiErr.status).toBe(422)
    expect(apiErr.code).toBe('validation_error')
    expect(apiErr.message).toBe('Invalid input')
    expect(apiErr.requestId).toBe('req_42')
    expect(apiErr.fieldErrors).toEqual({ title: 'Too short', reward_amount: 'Must be positive' })
  })

  it('falls back gracefully for non-envelope errors and network failures', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('<html>Bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }),
    )
    const err = (await http.get('/health').catch((e: unknown) => e)) as ApiError
    expect(err.status).toBe(502)
    expect(err.code).toBe('internal_error')

    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const netErr = (await http.get('/bounties').catch((e: unknown) => e)) as ApiError
    expect(netErr.code).toBe('network_error')
    expect(errorMessage(netErr)).toMatch(/cannot reach/i)
  })

  it('returns undefined for 204 responses', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(http.post('/auth/logout')).resolves.toBeUndefined()
  })
})

describe('401 → refresh → retry', () => {
  const expired = () =>
    jsonResponse({ error: { code: 'token_expired', message: 'Expired' } }, { status: 401 })

  it('refreshes once for concurrent 401s (single flight) and retries each request', async () => {
    let refreshCalls = 0
    const seen = new Map<string, number>()
    fetchMock.mockImplementation(async (url) => {
      if (url.endsWith('/auth/refresh')) {
        refreshCalls++
        await new Promise((r) => setTimeout(r, 10))
        return jsonResponse({ id: 'me' })
      }
      const n = (seen.get(url) ?? 0) + 1
      seen.set(url, n)
      return n === 1 ? expired() : jsonResponse({ url })
    })

    const results = await Promise.all([http.get('/a'), http.get('/b'), http.get('/c')])

    expect(refreshCalls).toBe(1)
    expect(results).toEqual([{ url: '/api/v1/a' }, { url: '/api/v1/b' }, { url: '/api/v1/c' }])
    expect(seen.get('/api/v1/a')).toBe(2)
  })

  it('logs out (auth failure handler) when the refresh fails, without looping', async () => {
    const onFail = vi.fn()
    setAuthFailureHandler(onFail)
    fetchMock.mockImplementation(async (url) =>
      url.endsWith('/auth/refresh')
        ? jsonResponse({ error: { code: 'not_authenticated', message: 'No session' } }, { status: 401 })
        : jsonResponse({ error: { code: 'not_authenticated', message: 'Login required' } }, { status: 401 }),
    )

    const err = (await http.get('/auth/me').catch((e: unknown) => e)) as ApiError
    expect(err.status).toBe(401)
    expect(onFail).toHaveBeenCalledTimes(1)
    // original + refresh only: no retry after a failed refresh
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not refresh for login failures or non-auth 401 codes', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: 'not_authenticated', message: 'Bad credentials' } }, { status: 401 }),
    )
    await expect(http.post('/auth/login', { email: 'a', password: 'b' })).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    fetchMock.mockReset()
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: 'forbidden', message: 'No' } }, { status: 401 }),
    )
    await expect(apiRequest('/admin/overview')).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('buildQuery', () => {
  it('drops empty values and joins arrays with commas', () => {
    expect(
      buildQuery({
        q: '',
        skills: ['rust', 'go'],
        page: 2,
        funded_only: true,
        status: [],
        x: undefined,
        y: null,
      }),
    ).toBe('?skills=rust%2Cgo&page=2&funded_only=true')
    expect(buildQuery({})).toBe('')
  })
})

describe('friendly messages for chain / wallet error codes', () => {
  it('keeps object-shaped details (contract_rejected) and names the contract error', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'contract_rejected',
            message: 'This contributor has already been paid for this bounty.',
            details: { contract_error: 'AlreadyPaid' },
          },
        },
        { status: 422 },
      ),
    )
    const err = (await http.post('/bounties/b1/chain/prepare', {}).catch((e) => e)) as ApiError
    expect(err.contractError).toBe('AlreadyPaid')
    expect(err.details).toEqual([])
    expect(errorMessage(err)).toBe('This contributor has already been paid for this bounty. (AlreadyPaid)')
  })

  it('maps wallet and infrastructure codes to actionable copy', () => {
    const make = (code: string, message = 'raw') => new ApiError({ status: 422, code, message })
    expect(errorMessage(make('wallet_not_verified'))).toMatch(/not linked to your account/)
    expect(errorMessage(make('account_not_found'))).toMatch(/Friendbot/)
    expect(errorMessage(make('signature_invalid'))).toMatch(/does not match/)
    expect(errorMessage(make('escrow_unverified'))).toMatch(/not created by BountyFlow/)
    expect(errorMessage(make('service_unavailable'))).toMatch(/temporarily unavailable/)
    expect(errorMessage(make('payload_too_large'))).toMatch(/too much data/)
    // wrong_wallet's server message names the wallet to use, so it is kept.
    expect(errorMessage(make('wrong_wallet', 'Sign with GABC…WXYZ.'))).toBe('Sign with GABC…WXYZ.')
  })
})
