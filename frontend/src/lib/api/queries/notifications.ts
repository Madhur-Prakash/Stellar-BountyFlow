import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { notificationsApi } from '../endpoints'
import type { NotificationListParams, UpdateNotificationPreferencesRequest } from '../types'
import { qk } from './keys'

export function useNotifications(
  params: NotificationListParams = {},
  options: { enabled?: boolean; poll?: boolean } = {},
) {
  return useQuery({
    queryKey: qk.notifications.list(params),
    queryFn: () => notificationsApi.list(params),
    enabled: options.enabled ?? true,
    refetchInterval: options.poll ? 60_000 : false,
    placeholderData: keepPreviousData,
  })
}

/** Lightweight unread counter for the top bar bell (polls every 60s). */
export function useUnreadNotificationCount(enabled: boolean) {
  const q = useNotifications({ unread_only: true, page: 1, page_size: 5 }, { enabled, poll: true })
  return { ...q, count: q.data?.unread_count ?? 0 }
}

export function useMarkNotificationRead() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.notifications.all }),
  })
}

export function useMarkAllNotificationsRead() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.notifications.all }),
  })
}

export function useNotificationPreferences(enabled = true) {
  return useQuery({
    queryKey: qk.notifications.preferences,
    queryFn: () => notificationsApi.getPreferences(),
    enabled,
  })
}

export function useUpdateNotificationPreferences() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateNotificationPreferencesRequest) => notificationsApi.updatePreferences(body),
    onSuccess: (prefs) => client.setQueryData(qk.notifications.preferences, prefs),
  })
}
