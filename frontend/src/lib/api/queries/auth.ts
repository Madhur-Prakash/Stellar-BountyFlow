import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { useAuthUi } from '@/stores/auth-ui'

import { isApiError } from '../client'
import { authApi } from '../endpoints'
import type { LoginRequest, Me, RegisterRequest, ResetPasswordRequest } from '../types'
import { PRIVATE_QUERY_ROOTS, qk } from './keys'

/** Fetches the current user; resolves to `null` (not an error) when anonymous. */
export async function fetchMeOrNull(): Promise<Me | null> {
  try {
    return await authApi.me()
  } catch (e) {
    if (isApiError(e) && (e.status === 401 || e.status === 403)) return null
    throw e
  }
}

export function useMe() {
  return useQuery({
    queryKey: qk.auth.me,
    queryFn: fetchMeOrNull,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

/** Removes every private query and marks the viewer as anonymous. */
export function clearPrivateCache(client: QueryClient) {
  // Never *remove* the `me` query: it may be mid-fetch (a failed refresh runs
  // inside its queryFn), and removing it would orphan every `useMe()` observer
  // in a permanent pending state ("Checking your session…"). Overwrite it.
  const isMe = (key: readonly unknown[]) =>
    key.length === qk.auth.me.length && key.every((k, i) => k === qk.auth.me[i])
  for (const root of PRIVATE_QUERY_ROOTS) {
    client.removeQueries({ queryKey: [root], predicate: (q) => !isMe(q.queryKey) })
  }
  client.setQueryData(qk.auth.me, null)
  // Public bounty payloads embed viewer-specific fields (viewer, is_bookmarked).
  client.invalidateQueries({ queryKey: qk.bounties.all })
}

function useSetMe() {
  const client = useQueryClient()
  return (me: Me) => {
    useAuthUi.getState().setSigningOut(false)
    client.setQueryData(qk.auth.me, me)
    client.invalidateQueries({ queryKey: qk.bounties.all })
  }
}

export function useLogin() {
  const setMe = useSetMe()
  return useMutation({ mutationFn: (body: LoginRequest) => authApi.login(body), onSuccess: setMe })
}

export function useRegister() {
  const setMe = useSetMe()
  return useMutation({ mutationFn: (body: RegisterRequest) => authApi.register(body), onSuccess: setMe })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => clearPrivateCache(client),
  })
}

export function useVerifyEmail() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => authApi.verifyEmail({ token }),
    onSuccess: (res) => {
      if ('id' in res) client.setQueryData(qk.auth.me, res)
      else client.invalidateQueries({ queryKey: qk.auth.me })
    },
  })
}

export function useResendVerification() {
  return useMutation({ mutationFn: () => authApi.resendVerification() })
}

export function useForgotPassword() {
  return useMutation({ mutationFn: (email: string) => authApi.forgotPassword({ email }) })
}

export function useResetPassword() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: ResetPasswordRequest) => authApi.resetPassword(body),
    // All sessions are revoked server-side.
    onSuccess: () => clearPrivateCache(client),
  })
}

export function useSessions(enabled = true) {
  return useQuery({ queryKey: qk.auth.sessions, queryFn: () => authApi.sessions(), enabled })
}

export function useRevokeSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => authApi.revokeSession(sessionId),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.auth.sessions }),
  })
}
