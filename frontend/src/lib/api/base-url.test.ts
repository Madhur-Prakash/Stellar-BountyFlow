import { describe, expect, it } from 'vitest'

/**
 * Mirrors `resolveBase` in client.ts. The rule it encodes: an origin on its own gets the versioned
 * prefix appended, because giving only the origin is the obvious mistake and produced requests to
 * `/config/public` — a 404 on every call, with an error message about session tokens that pointed
 * nowhere near the cause.
 */
const API_PREFIX = '/api/v1'

function resolveBase(raw: string | undefined): string {
  const value = raw?.trim().replace(/\/+$/, '')
  if (!value) return API_PREFIX
  if (!/^https?:\/\//i.test(value)) return value
  const { origin, pathname } = new URL(value)
  return pathname === '/' ? `${origin}${API_PREFIX}` : value
}

describe('API base URL', () => {
  it('defaults to the same-origin versioned path', () => {
    expect(resolveBase(undefined)).toBe('/api/v1')
    expect(resolveBase('')).toBe('/api/v1')
    expect(resolveBase('   ')).toBe('/api/v1')
  })

  it('keeps a path exactly as written', () => {
    expect(resolveBase('/api/v1')).toBe('/api/v1')
    expect(resolveBase('/api/v1/')).toBe('/api/v1')
  })

  it('adds the prefix to a bare origin', () => {
    expect(resolveBase('https://api.example.com')).toBe('https://api.example.com/api/v1')
    expect(resolveBase('https://api.example.com/')).toBe('https://api.example.com/api/v1')
  })

  it('leaves an absolute URL that already carries a path alone', () => {
    expect(resolveBase('https://api.example.com/api/v1')).toBe('https://api.example.com/api/v1')
    expect(resolveBase('https://api.example.com/api/v1/')).toBe('https://api.example.com/api/v1')
    // A gateway mounting the API under its own path must not have /api/v1 forced onto it.
    expect(resolveBase('https://gw.example.com/bountyflow')).toBe('https://gw.example.com/bountyflow')
  })
})
