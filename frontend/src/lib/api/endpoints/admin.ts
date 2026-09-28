import { http, seg } from '../client'
import type {
  AdminBountiesParams,
  AdminDisputesParams,
  AdminOverview,
  AdminReportsParams,
  AdminTransactionsParams,
  AdminUpdateUserRequest,
  AdminUser,
  AdminUsersParams,
  AuditLog,
  AuditLogParams,
  BlockchainTransaction,
  BountyDetail,
  BountySummary,
  Dispute,
  ModerateBountyRequest,
  Page,
  Report,
  ResolveReportRequest,
} from '../types'

export const adminApi = {
  overview: () => http.get<AdminOverview>('/admin/overview'),
  users: (params?: AdminUsersParams) => http.get<Page<AdminUser>>('/admin/users', params),
  updateUser: (id: string, body: AdminUpdateUserRequest) =>
    http.patch<AdminUser>(`/admin/users/${seg(id)}`, body),
  bounties: (params?: AdminBountiesParams) => http.get<Page<BountySummary>>('/admin/bounties', params),
  moderateBounty: (id: string, body: ModerateBountyRequest) =>
    http.post<BountyDetail>(`/admin/bounties/${seg(id)}/moderate`, body),
  reports: (params?: AdminReportsParams) => http.get<Page<Report>>('/admin/reports', params),
  resolveReport: (id: string, body: ResolveReportRequest) =>
    http.post<Report>(`/admin/reports/${seg(id)}/resolve`, body),
  disputes: (params?: AdminDisputesParams) => http.get<Page<Dispute>>('/admin/disputes', params),
  transactions: (params?: AdminTransactionsParams) =>
    http.get<Page<BlockchainTransaction>>('/admin/transactions', params),
  auditLogs: (params?: AuditLogParams) => http.get<Page<AuditLog>>('/admin/audit-logs', params),
}
