import type { ApiErrorCode, ErrorEnvelope, ValidationErrorDetail } from './types'

/**
 * Fetch wrapper implementing the conventions in docs/api.md:
 * - cookies always sent (`credentials: "include"`)
 * - `X-CSRF-Token` (double-submit, from the `bf_csrf` cookie) on mutating requests
 * - typed `ApiError` built from the `{ error: {...} }` envelope
 * - single-flight `POST /auth/refresh` on 401 `token_expired | not_authenticated`,
 *   then one retry; if the refresh fails the registered auth-failure handler runs.
 */

const RAW_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
export const API_BASE_URL = (RAW_BASE && RAW_BASE.length > 0 ? RAW_BASE : '/api/v1').replace(/\/+$/, '')

/** Health endpoints are not versioned; they live at the API origin root. */
export const HEALTH_BASE_URL = /^https?:\/\//i.test(API_BASE_URL) ? new URL(API_BASE_URL).origin : ''

export const CSRF_COOKIE = 'bf_csrf'
export const CSRF_HEADER = 'X-CSRF-Token'

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const REFRESHABLE_CODES = new Set<string>(['token_expired', 'not_authenticated'])
/** Requests that must never trigger a refresh-and-retry cycle. */
const NO_REFRESH_PATHS = ['/auth/refresh', '/auth/login', '/auth/register', '/auth/logout']

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[]
export type QueryParams = Record<string, QueryValue>

export class ApiError extends Error {
  readonly status: number
  readonly code: ApiErrorCode | 'network_error' | 'aborted' | (string & {})
  readonly details: unknown[]
  /** Object-shaped `details` (e.g. `{ contract_error: "AlreadyPaid" }` for `contract_rejected`). */
  readonly extra: Record<string, unknown>
  readonly requestId: string | null

  constructor(init: {
    status: number
    code: ApiError['code']
    message: string
    details?: unknown[] | null
    extra?: Record<string, unknown> | null
    requestId?: string | null
  }) {
    super(init.message)
    this.name = 'ApiError'
    this.status = init.status
    this.code = init.code
    this.details = init.details ?? []
    this.extra = init.extra ?? {}
    this.requestId = init.requestId ?? null
  }

  /** Contract error name for `contract_rejected` (e.g. "AlreadyPaid"), when the API sent one. */
  get contractError(): string | null {
    const v = this.extra.contract_error
    return typeof v === 'string' && v ? v : null
  }

  /** `validation_error.details` → `{ field: message }` map (first message wins). */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    for (const d of this.details) {
      if (d && typeof d === 'object' && 'field' in d && 'message' in d) {
        const { field, message } = d as ValidationErrorDetail
        if (typeof field === 'string' && !(field in out)) out[field] = String(message)
      }
    }
    return out
  }

  get isUnauthenticated() {
    return this.status === 401
  }
  get isForbidden() {
    return this.status === 403
  }
  get isNotFound() {
    return this.status === 404
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

/** True for the API's 403 `email_not_verified` error (e.g. when publishing a bounty). */
export function isEmailNotVerifiedError(e: unknown): boolean {
  return isApiError(e) && e.code === 'email_not_verified'
}

/**
 * Friendly copy for API error codes whose raw message is technical or
 * missing. Codes whose server message is already user-facing (e.g.
 * `wrong_wallet`, which names the wallet to use) keep it.
 */
const FRIENDLY: Partial<Record<string, (e: ApiError) => string>> = {
  network_error: () => 'Cannot reach the BountyFlow API. Check your connection and try again.',
  rate_limited: () => 'Too many requests. Please wait a moment and try again.',
  csrf_failed: () => 'Your session security token expired. Refresh the page and try again.',
  email_not_verified: () =>
    'Verify your email address before doing this. Check your inbox or resend the verification email.',
  contributor_wallet_missing: (e) =>
    e.message ||
    'This contributor has not verified a Stellar wallet yet, so they cannot be assigned. Ask them to connect and verify a wallet first.',
  wallet_not_verified: () =>
    'This wallet is not linked to your account. Connect it and choose “Verify ownership” on your profile first.',
  wrong_wallet: (e) => e.message || 'Sign with the wallet recorded on this escrow.',
  account_not_found: () =>
    'This wallet account does not exist on the network yet. Fund it first (on Testnet, use Friendbot), then try again.',
  signature_invalid: () =>
    'The signed transaction does not match what BountyFlow prepared. Nothing was submitted; start the action again.',
  contract_rejected: (e) =>
    `${e.message || 'The escrow contract rejected this action.'}${e.contractError ? ` (${e.contractError})` : ''}`,
  escrow_unverified: () =>
    'This bounty’s on-chain escrow was not created by BountyFlow with the expected terms, so it cannot be used. Contact support.',
  service_unavailable: () => 'A required service is temporarily unavailable. Please try again in a moment.',
  payload_too_large: () => 'That is too much data to send at once. Shorten the text and try again.',
  method_not_allowed: () => 'That action is not available.',
}

/** Human-friendly message for any thrown value. */
export function errorMessage(e: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (isApiError(e)) {
    const friendly = FRIENDLY[e.code]
    if (friendly) return friendly(e)
    return e.message || fallback
  }
  if (e instanceof Error && e.message) return e.message
  return fallback
}

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  for (const part of document.cookie.split(';')) {
    const c = part.trim()
    if (c.startsWith(prefix)) return decodeURIComponent(c.slice(prefix.length))
  }
  return null
}

export function buildQuery(params?: QueryParams): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      if (value.length === 0) continue
      sp.set(key, value.join(','))
    } else {
      sp.set(key, String(value))
    }
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

// ---------------------------------------------------------------------------
// Auth failure + refresh coordination
// ---------------------------------------------------------------------------

type AuthFailureHandler = () => void
let authFailureHandler: AuthFailureHandler | null = null

/** Registered once by the app (clears cached `me` and auth UI state). */
export function setAuthFailureHandler(handler: AuthFailureHandler | null) {
  authFailureHandler = handler
}

let refreshInFlight: Promise<boolean> | null = null

/** Single-flight refresh: concurrent 401s share one `POST /auth/refresh`. */
export function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        })
        // Drain the body so the request completes (an unread body keeps it open).
        await res.text().catch(() => '')
        return res.ok
      } catch {
        return false
      }
    })().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

// ---------------------------------------------------------------------------
// Core request
// ---------------------------------------------------------------------------

export type RequestOptions = {
  method?: HttpMethod
  body?: unknown
  query?: QueryParams
  signal?: AbortSignal
  headers?: Record<string, string>
  /** Use the unversioned origin root (health endpoints). */
  root?: boolean
  /** Internal: skip the 401 → refresh → retry cycle. */
  skipRefresh?: boolean
}

async function parseError(res: Response): Promise<ApiError> {
  let envelope: Partial<ErrorEnvelope> | null
  try {
    const text = await res.text()
    envelope = text ? (JSON.parse(text) as Partial<ErrorEnvelope>) : null
  } catch {
    envelope = null
  }
  const err = envelope?.error
  if (err && typeof err === 'object' && typeof err.code === 'string') {
    const raw: unknown = err.details
    return new ApiError({
      status: res.status,
      code: err.code,
      message:
        typeof err.message === 'string' && err.message ? err.message : res.statusText || 'Request failed',
      details: Array.isArray(raw) ? raw : [],
      extra: raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null,
      requestId: err.request_id ?? res.headers.get('x-request-id'),
    })
  }
  return new ApiError({
    status: res.status,
    code: res.status >= 500 ? 'internal_error' : `http_${res.status}`,
    message: res.statusText || `Request failed with status ${res.status}`,
    requestId: res.headers.get('x-request-id'),
  })
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const base = options.root ? HEALTH_BASE_URL : API_BASE_URL
  const url = `${base}${path}${buildQuery(options.query)}`

  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  let body: BodyInit | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (MUTATING_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE)
    if (csrf) headers[CSRF_HEADER] = csrf
  }

  let res: Response
  try {
    res = await fetch(url, { method, headers, body, credentials: 'include', signal: options.signal })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError({ status: 0, code: 'aborted', message: 'Request was cancelled.' })
    }
    throw new ApiError({ status: 0, code: 'network_error', message: 'Network request failed.' })
  }

  if (res.ok) {
    if (res.status === 204 || res.status === 205) return undefined as T
    const text = await res.text()
    if (!text) return undefined as T
    try {
      return JSON.parse(text) as T
    } catch {
      throw new ApiError({
        status: res.status,
        code: 'internal_error',
        message: 'Malformed server response.',
      })
    }
  }

  const error = await parseError(res)

  const canRefresh =
    res.status === 401 &&
    REFRESHABLE_CODES.has(error.code) &&
    !options.skipRefresh &&
    !options.root &&
    !NO_REFRESH_PATHS.some((p) => path.startsWith(p))

  if (canRefresh) {
    const refreshed = await refreshSession()
    if (refreshed) {
      return apiRequest<T>(path, { ...options, skipRefresh: true })
    }
    authFailureHandler?.()
  }

  throw error
}

export const http = {
  get: <T>(path: string, query?: QueryParams, opts?: Omit<RequestOptions, 'method' | 'query'>) =>
    apiRequest<T>(path, { ...opts, method: 'GET', query }),
  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...opts, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...opts, method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...opts, method: 'PUT', body }),
  delete: <T>(path: string, opts?: Omit<RequestOptions, 'method'>) =>
    apiRequest<T>(path, { ...opts, method: 'DELETE' }),
}

/** Encode a path segment (ids, slugs, usernames, hashes). */
export const seg = (v: string) => encodeURIComponent(v)
