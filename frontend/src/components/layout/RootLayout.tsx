import { Outlet, ScrollRestoration } from 'react-router'

import { LoadingState } from './LoadingState'

/** Top-level route element: restores scroll per pathname. */
export function RootLayout() {
  return (
    <>
      <ScrollRestoration getKey={(location) => location.pathname} />
      <Outlet />
    </>
  )
}

/** Shown while the first lazy route module loads. */
export function RouteHydrateFallback() {
  return <LoadingState label="Loading BountyFlow" className="min-h-dvh" />
}
