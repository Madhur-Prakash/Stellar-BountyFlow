import type { Me } from '@/lib/api/types'

/** Only same-origin, absolute-path redirects are honoured (blocks open redirects). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next) return null
  if (!next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return null
  if (/^\/(login|register|forgot-password|reset-password)(\/|\?|$)/.test(next)) return null
  return next
}

export function loginPath(next?: string | null): string {
  const n = safeNext(next ?? null)
  return n ? `/login?next=${encodeURIComponent(n)}` : '/login'
}

/**
 * Where to land after login/registration. Accounts that have not finished
 * onboarding go there first, carrying the original destination along so the
 * onboarding page can continue to it afterwards.
 */
export function postLoginPath(me: Pick<Me, 'onboarding'>, next?: string | null): string {
  const n = safeNext(next ?? null)
  if (!me.onboarding.completed) {
    return n && !n.startsWith('/app/onboarding')
      ? `/app/onboarding?next=${encodeURIComponent(n)}`
      : '/app/onboarding'
  }
  return n ?? '/app'
}
