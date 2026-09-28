import { http } from '../client'
import type {
  ContributorAnalytics,
  MyAnalytics,
  PlatformAnalytics,
  PublicStats,
  RequesterAnalytics,
} from '../types'

export const analyticsApi = {
  public: () => http.get<PublicStats>('/analytics/public'),
  me: () => http.get<MyAnalytics>('/analytics/me'),
  requester: () => http.get<RequesterAnalytics>('/analytics/requester'),
  contributor: () => http.get<ContributorAnalytics>('/analytics/contributor'),
  platform: () => http.get<PlatformAnalytics>('/analytics/platform'),
}
