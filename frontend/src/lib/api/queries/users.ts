import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { usersApi } from '../endpoints'
import type { PageParams, UpdateMeRequest } from '../types'
import { qk } from './keys'

export function usePublicProfile(username: string | undefined) {
  return useQuery({
    queryKey: qk.users.profile(username ?? ''),
    queryFn: () => usersApi.getProfile(username!),
    enabled: !!username,
  })
}

export function useUserBounties(username: string | undefined, params: PageParams = {}) {
  return useQuery({
    queryKey: qk.users.bounties(username ?? '', params),
    queryFn: () => usersApi.getBounties(username!, params),
    enabled: !!username,
    placeholderData: keepPreviousData,
  })
}

export function useUserContributions(username: string | undefined, params: PageParams = {}) {
  return useQuery({
    queryKey: qk.users.contributions(username ?? '', params),
    queryFn: () => usersApi.getContributions(username!, params),
    enabled: !!username,
    placeholderData: keepPreviousData,
  })
}

export function useUserStats(username: string | undefined) {
  return useQuery({
    queryKey: qk.users.stats(username ?? ''),
    queryFn: () => usersApi.getStats(username!),
    enabled: !!username,
  })
}

export function useUpdateMe() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateMeRequest) => usersApi.updateMe(body),
    onSuccess: (me) => {
      client.setQueryData(qk.auth.me, me)
      client.invalidateQueries({ queryKey: qk.users.all })
    },
  })
}

export function useCompleteOnboarding() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => usersApi.completeOnboarding(),
    onSuccess: (me) => {
      client.setQueryData(qk.auth.me, me)
      client.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}
