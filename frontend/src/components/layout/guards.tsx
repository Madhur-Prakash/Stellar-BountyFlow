import { ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, Navigate, Outlet, useLocation, useSearchParams } from 'react-router'

import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/api/queries/auth'
import type { Permission } from '@/lib/api/types'
import { loginPath, postLoginPath } from '@/lib/auth-redirect'
import { hasPermission } from '@/lib/permissions'
import { useAuthUi } from '@/stores/auth-ui'

import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'

/** Renders children (or <Outlet/>) only for authenticated users; otherwise → /login?next=… */
export function RequireAuth({ children }: { children?: ReactNode }) {
  const { data: me, isPending, isError, error, refetch } = useMe()
  const location = useLocation()
  const signingOut = useAuthUi((s) => s.signingOut)

  if (isPending) return <LoadingState label="Checking your session" className="min-h-[50vh]" />
  if (isError)
    return <ErrorState error={error} title="Could not verify your session" onRetry={() => refetch()} />
  if (!me) {
    // A deliberate sign-out goes home; an expired or missing session goes to login and comes back.
    if (signingOut) return <Navigate to="/" replace />
    return <Navigate to={loginPath(`${location.pathname}${location.search}${location.hash}`)} replace />
  }
  return children ? <>{children}</> : <Outlet />
}

/**
 * Renders children only when the viewer holds `permission` (from
 * `Me.permissions`). Assumes RequireAuth above it. `/admin/*` uses
 * "bounty:moderate", which every staff member holds.
 */
export function RequirePermission({
  permission,
  children,
}: {
  permission: Permission
  children?: ReactNode
}) {
  const { data: me, isPending } = useMe()
  if (isPending) return <LoadingState label="Checking permissions" className="min-h-[50vh]" />
  if (!hasPermission(me, permission)) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <EmptyState
          icon={ShieldCheck}
          title="You don’t have access to this area"
          description="This section is limited to BountyFlow moderators and administrators."
          action={
            <Button asChild variant="outline">
              <Link to="/app">Back to dashboard</Link>
            </Button>
          }
        />
      </div>
    )
  }
  return children ? <>{children}</> : <Outlet />
}

/**
 * For /login, /register…: signed-in users are sent on to ?next= or their
 * dashboard. The page renders immediately while the session check runs, so a
 * slow or unreachable API never blocks the sign-in form.
 */
export function RedirectIfAuthed({ children }: { children?: ReactNode }) {
  const { data: me } = useMe()
  const [params] = useSearchParams()
  if (me) return <Navigate to={postLoginPath(me, params.get('next'))} replace />
  return children ? <>{children}</> : <Outlet />
}
