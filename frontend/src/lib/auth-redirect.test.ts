import { describe, expect, it } from 'vitest'

import { makeMe } from '@/test/fixtures'

import { loginPath, postLoginPath, safeNext } from './auth-redirect'

describe('auth redirects', () => {
  it('accepts only same-origin absolute paths', () => {
    expect(safeNext('/app/saved?x=1')).toBe('/app/saved?x=1')
    expect(safeNext('https://evil.test')).toBeNull()
    expect(safeNext('//evil.test')).toBeNull()
    expect(safeNext('/\\evil.test')).toBeNull()
    expect(safeNext('/login?next=/app')).toBeNull()
    expect(safeNext(null)).toBeNull()
  })

  it('builds login URLs with an encoded return path', () => {
    expect(loginPath('/bounties/abc')).toBe('/login?next=%2Fbounties%2Fabc')
    expect(loginPath('https://evil.test')).toBe('/login')
  })

  it('routes to onboarding until it is completed', () => {
    const incomplete = makeMe({ onboarding: { ...makeMe().onboarding, completed: false } })
    expect(postLoginPath(incomplete, '/app/saved')).toBe('/app/onboarding?next=%2Fapp%2Fsaved')
    expect(postLoginPath(incomplete, null)).toBe('/app/onboarding')
    expect(postLoginPath(incomplete, 'https://evil.test')).toBe('/app/onboarding')
    expect(postLoginPath(makeMe(), '/app/saved')).toBe('/app/saved')
    expect(postLoginPath(makeMe(), null)).toBe('/app')
  })
})
