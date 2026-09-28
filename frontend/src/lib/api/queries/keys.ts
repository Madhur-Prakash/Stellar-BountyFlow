import type {
  AdminBountiesParams,
  AdminDisputesParams,
  AdminReportsParams,
  AdminTransactionsParams,
  AdminUsersParams,
  ApplicationListParams,
  AuditLogParams,
  BountyListParams,
  MyBountiesParams,
  NotificationListParams,
  PageParams,
  PaymentsParams,
  SubmissionListParams,
} from '../types'

/**
 * Query-key factory. Keys are hierarchical so a mutation can invalidate a
 * whole domain (e.g. `qk.bounties.all`) or one precise entry.
 */
export const qk = {
  health: ['health'] as const,
  config: ['config', 'public'] as const,

  auth: {
    all: ['auth'] as const,
    me: ['auth', 'me'] as const,
    sessions: ['auth', 'sessions'] as const,
  },

  users: {
    all: ['users'] as const,
    profile: (username: string) => ['users', username, 'profile'] as const,
    bounties: (username: string, p: PageParams = {}) => ['users', username, 'bounties', p] as const,
    contributions: (username: string, p: PageParams = {}) => ['users', username, 'contributions', p] as const,
    stats: (username: string) => ['users', username, 'stats'] as const,
  },

  wallets: {
    all: ['wallets'] as const,
  },

  bounties: {
    all: ['bounties'] as const,
    list: (p: BountyListParams = {}) => ['bounties', 'list', p] as const,
    featured: ['bounties', 'featured'] as const,
    mine: (p: MyBountiesParams = {}) => ['bounties', 'mine', p] as const,
    saved: (p: PageParams = {}) => ['bounties', 'saved', p] as const,
    detail: (idOrSlug: string) => ['bounties', 'detail', idOrSlug] as const,
    activity: (id: string, p: PageParams = {}) => ['bounties', 'detail', id, 'activity', p] as const,
    funding: (id: string) => ['bounties', 'detail', id, 'funding'] as const,
    transactions: (id: string) => ['bounties', 'detail', id, 'transactions'] as const,
    applications: (id: string, p: ApplicationListParams = {}) =>
      ['bounties', 'detail', id, 'applications', p] as const,
    submissions: (id: string, p: PageParams = {}) => ['bounties', 'detail', id, 'submissions', p] as const,
  },

  applications: {
    all: ['applications'] as const,
    mine: (p: ApplicationListParams = {}) => ['applications', 'mine', p] as const,
  },

  submissions: {
    all: ['submissions'] as const,
    mine: (p: SubmissionListParams = {}) => ['submissions', 'mine', p] as const,
    detail: (id: string) => ['submissions', 'detail', id] as const,
  },

  transactions: {
    all: ['transactions'] as const,
    mine: (p: PageParams = {}) => ['transactions', 'mine', p] as const,
    detail: (idOrHash: string) => ['transactions', 'detail', idOrHash] as const,
  },

  payments: {
    all: ['payments'] as const,
    mine: (p: PaymentsParams = {}) => ['payments', 'mine', p] as const,
  },

  notifications: {
    all: ['notifications'] as const,
    list: (p: NotificationListParams = {}) => ['notifications', 'list', p] as const,
    preferences: ['notifications', 'preferences'] as const,
  },

  analytics: {
    all: ['analytics'] as const,
    public: ['analytics', 'public'] as const,
    me: ['analytics', 'me'] as const,
    requester: ['analytics', 'requester'] as const,
    contributor: ['analytics', 'contributor'] as const,
    platform: ['analytics', 'platform'] as const,
  },

  dashboard: ['dashboard'] as const,

  disputes: {
    all: ['disputes'] as const,
    mine: ['disputes', 'mine'] as const,
    detail: (id: string) => ['disputes', 'detail', id] as const,
  },

  admin: {
    all: ['admin'] as const,
    overview: ['admin', 'overview'] as const,
    users: (p: AdminUsersParams = {}) => ['admin', 'users', p] as const,
    bounties: (p: AdminBountiesParams = {}) => ['admin', 'bounties', p] as const,
    reports: (p: AdminReportsParams = {}) => ['admin', 'reports', p] as const,
    disputes: (p: AdminDisputesParams = {}) => ['admin', 'disputes', p] as const,
    transactions: (p: AdminTransactionsParams = {}) => ['admin', 'transactions', p] as const,
    auditLogs: (p: AuditLogParams = {}) => ['admin', 'audit-logs', p] as const,
  },
}

/** Domains that hold per-user private data; dropped from the cache on logout. */
export const PRIVATE_QUERY_ROOTS = [
  'auth',
  'wallets',
  'applications',
  'submissions',
  'transactions',
  'payments',
  'notifications',
  'dashboard',
  'disputes',
  'admin',
] as const
