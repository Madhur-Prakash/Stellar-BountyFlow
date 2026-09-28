import { RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

import { Logo } from '@/components/brand/Logo'
import { Button } from '@/components/ui/button'
import NotFoundPage from '@/features/public/NotFoundPage'

function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="flex h-16 items-center px-4 sm:px-6">
        <Link to="/" aria-label="BountyFlow home" className="inline-flex rounded-md">
          <Logo />
        </Link>
      </header>
      <main className="flex flex-1 flex-col">{children}</main>
    </div>
  )
}

/** Last-resort error screen for routing / render errors (and failed lazy chunks after a deploy). */
export function RouteErrorBoundary() {
  const error = useRouteError()

  if (isRouteErrorResponse(error) && error.status === 404) {
    return (
      <Frame>
        <NotFoundPage />
      </Frame>
    )
  }

  const chunkError =
    error instanceof Error &&
    /(dynamically imported module|Loading chunk|Importing a module script failed)/i.test(error.message)

  return (
    <Frame>
      <div
        role="alert"
        className="mx-auto flex w-full max-w-md flex-col items-center px-4 py-20 text-center sm:py-28"
      >
        <span className="rounded-[4px] border bg-card px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
          {chunkError ? 'Update' : 'Error'}
        </span>
        <h1 className="font-display mt-4 text-[1.625rem] leading-tight">
          {chunkError ? 'A new version is available' : 'Something went wrong'}
        </h1>
        <p className="mt-2 max-w-sm text-sm text-muted-foreground">
          {chunkError
            ? 'BountyFlow has been updated. Reload to get the latest version.'
            : 'This page couldn’t be displayed. Try reloading it.'}
        </p>
        {import.meta.env.DEV && error instanceof Error && (
          <pre className="mt-5 max-h-40 w-full overflow-auto rounded-lg border bg-surface p-3 text-left font-mono text-xs">
            {error.message}
          </pre>
        )}
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button onClick={() => window.location.reload()}>
            <RotateCw aria-hidden /> Reload
          </Button>
          <Button asChild variant="outline">
            <a href="/">Go home</a>
          </Button>
        </div>
      </div>
    </Frame>
  )
}
