import { http, seg } from '../client'
import type {
  NotificationListParams,
  NotificationPage,
  NotificationPreferences,
  UpdateNotificationPreferencesRequest,
} from '../types'

export const notificationsApi = {
  list: (params?: NotificationListParams) =>
    http.get<NotificationPage>('/notifications', {
      unread_only: params?.unread_only ? true : undefined,
      page: params?.page,
      page_size: params?.page_size,
    }),
  markRead: (id: string) => http.post<void>(`/notifications/${seg(id)}/read`),
  markAllRead: () => http.post<void>('/notifications/read-all'),
  getPreferences: () => http.get<NotificationPreferences>('/notification-preferences'),
  updatePreferences: (body: UpdateNotificationPreferencesRequest) =>
    http.patch<NotificationPreferences>('/notification-preferences', body),
}
