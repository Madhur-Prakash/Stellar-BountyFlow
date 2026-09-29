import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { recommendationsApi, savedSearchesApi, skillsApi } from '../endpoints'
import type {
  BountyListParams,
  CreateSavedSearchRequest,
  SavedSearch,
  UpdateSavedSearchRequest,
} from '../types'
import { qk } from './keys'

export function useSavedSearches(enabled = true) {
  return useQuery({
    queryKey: qk.savedSearches.list,
    queryFn: () => savedSearchesApi.list(),
    enabled,
  })
}

export function useSavedSearch(id: string | null | undefined) {
  return useQuery({
    queryKey: qk.savedSearches.detail(id ?? ''),
    queryFn: () => savedSearchesApi.get(id!),
    enabled: !!id,
  })
}

/** Keeps the list and the one search in step after any change. */
function useSavedSearchCache() {
  const client = useQueryClient()
  return (search: SavedSearch) => {
    client.setQueryData(qk.savedSearches.detail(search.id), search)
    client.invalidateQueries({ queryKey: qk.savedSearches.list })
  }
}

export function useCreateSavedSearch() {
  const client = useQueryClient()
  const store = useSavedSearchCache()
  return useMutation({
    mutationFn: (body: CreateSavedSearchRequest) => savedSearchesApi.create(body),
    onSuccess: (search) => {
      store(search)
      // Choosing email for a search turns saved-search emails on in the notification settings.
      client.invalidateQueries({ queryKey: qk.notifications.preferences })
    },
  })
}

export function useUpdateSavedSearch() {
  const client = useQueryClient()
  const store = useSavedSearchCache()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateSavedSearchRequest }) =>
      savedSearchesApi.update(id, body),
    onSuccess: (search) => {
      store(search)
      client.invalidateQueries({ queryKey: qk.notifications.preferences })
    },
  })
}

export function useDeleteSavedSearch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => savedSearchesApi.remove(id),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: qk.savedSearches.detail(id) })
      client.invalidateQueries({ queryKey: qk.savedSearches.list })
    },
  })
}

export function useMarkSavedSearchViewed() {
  const store = useSavedSearchCache()
  return useMutation({
    mutationFn: (id: string) => savedSearchesApi.markViewed(id),
    onSuccess: store,
  })
}

export function useUnsubscribeSavedSearch() {
  return useMutation({ mutationFn: (token: string) => savedSearchesApi.unsubscribe(token) })
}

export function useRecommendations(params: BountyListParams = {}, enabled = true) {
  return useQuery({
    queryKey: qk.recommendations.list(params),
    queryFn: () => recommendationsApi.list(params),
    enabled,
    placeholderData: keepPreviousData,
  })
}

export function useRelatedSkills(skills: string[]) {
  return useQuery({
    queryKey: qk.skills.related(skills),
    queryFn: () => skillsApi.related(skills),
    enabled: skills.length > 0,
    staleTime: 5 * 60_000,
  })
}
