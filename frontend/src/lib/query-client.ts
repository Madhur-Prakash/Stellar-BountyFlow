import { QueryClient } from '@tanstack/react-query'

import { isApiError, setAuthFailureHandler } from '@/lib/api/client'
import { clearPrivateCache } from '@/lib/api/queries/auth'
import { qk } from '@/lib/api/queries/keys'
import { useAuthUi } from '@/stores/auth-ui'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Client errors (4xx) are deterministic; only retry network/5xx, twice.
          if (isApiError(error) && error.status >= 400 && error.status < 500) return false
          return failureCount < 2
        },
      },
      mutations: { retry: false },
    },
  })
}

export const queryClient = createQueryClient()

/** When a refresh fails, drop private data and remember that the session expired. */
export function installAuthFailureHandler(client: QueryClient = queryClient) {
  setAuthFailureHandler(() => {
    const hadUser = !!client.getQueryData(qk.auth.me)
    clearPrivateCache(client)
    if (hadUser) useAuthUi.getState().markSessionExpired()
  })
}
