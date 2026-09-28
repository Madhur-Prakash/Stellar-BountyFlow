import { useQuery } from '@tanstack/react-query'

import { configApi, healthApi } from '../endpoints'
import { qk } from './keys'

/** Public runtime configuration (network, explorer, blockchain mode). Cached for the session. */
export function usePublicConfig() {
  return useQuery({
    queryKey: qk.config,
    queryFn: () => configApi.getPublic(),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: 2,
  })
}

export function useHealthReady(enabled = true) {
  return useQuery({ queryKey: qk.health, queryFn: () => healthApi.ready(), enabled, refetchInterval: 30_000 })
}
