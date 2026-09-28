import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider, type RouteObject } from 'react-router'

import { TooltipProvider } from '@/components/ui/tooltip'
import { qk } from '@/lib/api/queries/keys'
import type { Me, PublicConfig } from '@/lib/api/types'

import { makeConfig } from './fixtures'

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: Infinity },
      mutations: { retry: false },
    },
  })
}

type Options = {
  /** Initial URL, e.g. "/bounties?q=rust". */
  route?: string
  /** Route pattern for `ui` (default "*"). */
  path?: string
  /** Extra sibling routes (e.g. a /login target to assert redirects). */
  routes?: RouteObject[]
  /** Pre-seeded viewer: `null` = anonymous. */
  me?: Me | null
  config?: PublicConfig
  client?: QueryClient
}

/** Renders `ui` inside a memory data-router with Query + Tooltip providers. */
export function renderWithProviders(ui: ReactElement, opts: Options = {}) {
  const client = opts.client ?? createTestQueryClient()
  if (opts.me !== undefined) client.setQueryData(qk.auth.me, opts.me)
  client.setQueryData(qk.config, opts.config ?? makeConfig())

  const router = createMemoryRouter([{ path: opts.path ?? '*', element: ui }, ...(opts.routes ?? [])], {
    initialEntries: [opts.route ?? '/'],
  })
  const utils = render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...utils, router, client }
}
