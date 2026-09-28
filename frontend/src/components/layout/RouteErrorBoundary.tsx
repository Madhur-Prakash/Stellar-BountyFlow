import { CircleAlert, RotateCw } from 'lucide-react'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

import { Logo } from '@/components/brand/Logo'
import { Button } from '@/components/ui/button'
import NotFoundPage from '@/features/public/NotFoundPage'

/** Last-resort error screen for routing / render errors (and failed lazy chunks after a deploy). */
export function RouteErrorBoundary() {
  const error = useRouteError()

  if (isRouteErrorResponse(error) && error.status === 404) {
    return (
      <div className="min-h-dvh">
        <div className="mx-auto flex h-16 max-w-384 items-center px-4 sm:px-6 lg:px-8 2xl:px-12">
          <Link to="/" aria-label="BountyFlow home">
            <Logo />
          </Link>
        </div>
        <NotFoundPage />
      </div>
    )
  }

  const chunkError =
    error instanceof Error &&
    /(dynamically imported module|Loading chunk|Importing a module script failed)/i.test(error.message)

  return (
    <div className="flex min-h-dvh items-center justify-center px-4" role="alert">
      <div className="max-w-md text-center">
        <CircleAlert className="mx-auto size-8 text-destructive" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">
          {chunkError ? 'A new version is available' : 'Something went wrong'}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {chunkError
            ? 'BountyFlow was updated while this tab was open. Reload to get the latest version.'
            : 'An unexpected error stopped this page from rendering. Reloading usually fixes it; if not, head back home.'}
        </p>
        {import.meta.env.DEV && error instanceof Error && (
          <pre className="mt-4 max-h-40 overflow-auto rounded-lg border bg-surface p-3 text-left font-mono text-xs">
            {error.message}
          </pre>
        )}
        <div className="mt-6 flex justify-center gap-3">
          <Button onClick={() => window.location.reload()}>
            <RotateCw /> Reload
          </Button>
          <Button asChild variant="outline">
            <a href="/">Go home</a>
          </Button>
        </div>
      </div>
    </div>
  )
}
