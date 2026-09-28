import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { adminApi } from '../endpoints'
import type {
  AdminBountiesParams,
  AdminDisputesParams,
  AdminReportsParams,
  AdminTransactionsParams,
  AdminUpdateUserRequest,
  AdminUsersParams,
  AuditLogParams,
  ModerateBountyRequest,
  ResolveReportRequest,
} from '../types'
import { qk } from './keys'

export function useAdminOverview() {
  return useQuery({
    queryKey: qk.admin.overview,
    queryFn: () => adminApi.overview(),
    refetchInterval: 30_000,
  })
}

export function useAdminUsers(params: AdminUsersParams = {}) {
  return useQuery({
    queryKey: qk.admin.users(params),
    queryFn: () => adminApi.users(params),
    placeholderData: keepPreviousData,
  })
}

export function useAdminBounties(params: AdminBountiesParams = {}) {
  return useQuery({
    queryKey: qk.admin.bounties(params),
    queryFn: () => adminApi.bounties(params),
    placeholderData: keepPreviousData,
  })
}

export function useAdminReports(params: AdminReportsParams = {}) {
  return useQuery({
    queryKey: qk.admin.reports(params),
    queryFn: () => adminApi.reports(params),
    placeholderData: keepPreviousData,
  })
}

export function useAdminDisputes(params: AdminDisputesParams = {}) {
  return useQuery({
    queryKey: qk.admin.disputes(params),
    queryFn: () => adminApi.disputes(params),
    placeholderData: keepPreviousData,
  })
}

export function useAdminTransactions(params: AdminTransactionsParams = {}) {
  return useQuery({
    queryKey: qk.admin.transactions(params),
    queryFn: () => adminApi.transactions(params),
    placeholderData: keepPreviousData,
  })
}

export function useAuditLogs(params: AuditLogParams = {}) {
  return useQuery({
    queryKey: qk.admin.auditLogs(params),
    queryFn: () => adminApi.auditLogs(params),
    placeholderData: keepPreviousData,
  })
}

export function useAdminUpdateUser() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AdminUpdateUserRequest }) => adminApi.updateUser(id, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['admin', 'users'] }),
  })
}

export function useModerateBounty() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ModerateBountyRequest }) =>
      adminApi.moderateBounty(id, body),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: qk.admin.all })
      client.invalidateQueries({ queryKey: qk.bounties.all })
    },
  })
}

export function useResolveReport() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ResolveReportRequest }) =>
      adminApi.resolveReport(id, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['admin', 'reports'] }),
  })
}
