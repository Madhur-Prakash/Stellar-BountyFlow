import { useQuery } from '@tanstack/react-query'

import { analyticsApi, dashboardApi } from '../endpoints'
import { qk } from './keys'

export function usePublicStats() {
  return useQuery({ queryKey: qk.analytics.public, queryFn: () => analyticsApi.public(), staleTime: 60_000 })
}

export function useMyAnalytics() {
  return useQuery({ queryKey: qk.analytics.me, queryFn: () => analyticsApi.me() })
}

export function useRequesterAnalytics() {
  return useQuery({ queryKey: qk.analytics.requester, queryFn: () => analyticsApi.requester() })
}

export function useContributorAnalytics() {
  return useQuery({ queryKey: qk.analytics.contributor, queryFn: () => analyticsApi.contributor() })
}

export function usePlatformAnalytics() {
  return useQuery({ queryKey: qk.analytics.platform, queryFn: () => analyticsApi.platform() })
}

export function useDashboard() {
  return useQuery({ queryKey: qk.dashboard, queryFn: () => dashboardApi.get() })
}
