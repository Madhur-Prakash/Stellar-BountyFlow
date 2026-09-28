import { http, seg } from '../client'
import type {
  BountySummary,
  Contribution,
  Me,
  Page,
  PageParams,
  PublicProfile,
  UpdateMeRequest,
  UserStats,
} from '../types'

export const usersApi = {
  getMe: () => http.get<Me>('/users/me'),
  updateMe: (body: UpdateMeRequest) => http.patch<Me>('/users/me', body),
  completeOnboarding: () => http.post<Me>('/users/me/onboarding/complete'),
  getProfile: (username: string) => http.get<PublicProfile>(`/users/${seg(username)}`),
  getBounties: (username: string, params?: PageParams) =>
    http.get<Page<BountySummary>>(`/users/${seg(username)}/bounties`, params),
  getContributions: (username: string, params?: PageParams) =>
    http.get<Page<Contribution>>(`/users/${seg(username)}/contributions`, params),
  getStats: (username: string) => http.get<UserStats>(`/users/${seg(username)}/stats`),
}
