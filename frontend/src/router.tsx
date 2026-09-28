import type { ComponentType } from 'react'
import { createBrowserRouter, type RouteObject } from 'react-router'

import { RedirectIfAuthed } from '@/components/layout/guards'
import { RootLayout, RouteHydrateFallback } from '@/components/layout/RootLayout'
import { RouteErrorBoundary } from '@/components/layout/RouteErrorBoundary'
import { LegacyGuideRedirect } from '@/components/layout/routes/LegacyGuideRedirect'
import NotFoundPage from '@/features/public/NotFoundPage'

/** Lazy route module: code-split per page, default export is the page component. */
const page = (load: () => Promise<{ default: ComponentType }>) => async () => {
  const mod = await load()
  return { Component: mod.default }
}

export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    errorElement: <RouteErrorBoundary />,
    HydrateFallback: RouteHydrateFallback,
    children: [
      // ---------------- Public site ----------------
      {
        lazy: page(() => import('@/components/layout/routes/MarketingRoute')),
        children: [
          { index: true, lazy: page(() => import('@/features/marketing/LandingPage')) },
          { path: 'bounties', lazy: page(() => import('@/features/public/marketplace/MarketplacePage')) },
          {
            path: 'bounties/:bountyId',
            lazy: page(() => import('@/features/public/bounty/BountyDetailPage')),
          },
          { path: 'u/:username', lazy: page(() => import('@/features/public/profile/PublicProfilePage')) },
          { path: 'how-it-works', lazy: page(() => import('@/features/marketing/HowItWorksPage')) },
          { path: 'about', lazy: page(() => import('@/features/marketing/AboutPage')) },
          { path: 'guide', lazy: page(() => import('@/features/marketing/GuidePage')) },
          { path: 'docs', element: <LegacyGuideRedirect /> },
          { path: 'terms', lazy: page(() => import('@/features/marketing/TermsPage')) },
          { path: 'privacy', lazy: page(() => import('@/features/marketing/PrivacyPage')) },
          { path: '*', element: <NotFoundPage /> },
        ],
      },

      // ---------------- Auth ----------------
      {
        lazy: page(() => import('@/components/layout/routes/AuthRoute')),
        children: [
          {
            element: <RedirectIfAuthed />,
            children: [
              { path: 'login', lazy: page(() => import('@/features/auth/LoginPage')) },
              { path: 'register', lazy: page(() => import('@/features/auth/RegisterPage')) },
              { path: 'forgot-password', lazy: page(() => import('@/features/auth/ForgotPasswordPage')) },
              { path: 'reset-password', lazy: page(() => import('@/features/auth/ResetPasswordPage')) },
            ],
          },
          { path: 'verify-email', lazy: page(() => import('@/features/auth/VerifyEmailPage')) },
        ],
      },

      // ---------------- Authenticated workspace ----------------
      {
        path: 'app',
        lazy: page(() => import('@/components/layout/routes/AppRoute')),
        children: [
          { index: true, lazy: page(() => import('@/features/app/DashboardPage')) },
          { path: 'onboarding', lazy: page(() => import('@/features/app/OnboardingPage')) },
          { path: 'bounties', lazy: page(() => import('@/features/app/bounties/MyBountiesPage')) },
          { path: 'bounties/create', lazy: page(() => import('@/features/app/bounties/CreateBountyPage')) },
          {
            path: 'bounties/:bountyId',
            lazy: page(() => import('@/features/app/bounties/ManageBountyPage')),
          },
          {
            path: 'bounties/:bountyId/edit',
            lazy: page(() => import('@/features/app/bounties/EditBountyPage')),
          },
          {
            path: 'bounties/:bountyId/applications',
            lazy: page(() => import('@/features/app/bounties/BountyApplicationsPage')),
          },
          {
            path: 'bounties/:bountyId/submissions',
            lazy: page(() => import('@/features/app/bounties/BountySubmissionsPage')),
          },
          { path: 'applications', lazy: page(() => import('@/features/app/ApplicationsPage')) },
          { path: 'submissions', lazy: page(() => import('@/features/app/SubmissionsPage')) },
          { path: 'payments', lazy: page(() => import('@/features/app/PaymentsPage')) },
          { path: 'transactions', lazy: page(() => import('@/features/app/TransactionsPage')) },
          { path: 'saved', lazy: page(() => import('@/features/app/SavedPage')) },
          { path: 'notifications', lazy: page(() => import('@/features/app/NotificationsPage')) },
          { path: 'profile', lazy: page(() => import('@/features/app/ProfilePage')) },
          { path: 'settings', lazy: page(() => import('@/features/app/SettingsPage')) },
          { path: 'analytics', lazy: page(() => import('@/features/app/AnalyticsPage')) },
          { path: '*', element: <NotFoundPage /> },
        ],
      },

      // ---------------- Staff console ----------------
      {
        path: 'admin',
        lazy: page(() => import('@/components/layout/routes/AdminRoute')),
        children: [
          { index: true, lazy: page(() => import('@/features/admin/AdminOverviewPage')) },
          { path: 'users', lazy: page(() => import('@/features/admin/AdminUsersPage')) },
          { path: 'bounties', lazy: page(() => import('@/features/admin/AdminBountiesPage')) },
          { path: 'reports', lazy: page(() => import('@/features/admin/AdminReportsPage')) },
          { path: 'disputes', lazy: page(() => import('@/features/admin/AdminDisputesPage')) },
          { path: 'transactions', lazy: page(() => import('@/features/admin/AdminTransactionsPage')) },
          { path: 'audit-logs', lazy: page(() => import('@/features/admin/AdminAuditLogsPage')) },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]

export function createAppRouter() {
  return createBrowserRouter(routes)
}
