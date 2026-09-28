import { useCallback, useState } from 'react'

import type { DisputeResolution, Role } from '@/lib/api/types'

/** Every admin list requests this many rows per page. */
export const ADMIN_PAGE_SIZE = 20

/** Radix Select items cannot use an empty string value, so "no filter" uses this sentinel. */
export const ALL_OPTION = '__all__'

export const ROLE_LABELS: Record<Role, string> = {
  USER: 'User',
  MODERATOR: 'Moderator',
  ADMIN: 'Admin',
}

export const DISPUTE_RESOLUTION_LABELS: Record<DisputeResolution, string> = {
  RELEASE_TO_CONTRIBUTOR: 'Release to contributor',
  REFUND_TO_REQUESTER: 'Refund to requester',
  DISMISSED: 'Dismiss',
}

/** Dispute states in which a moderator can still assign or resolve. */
export const OPEN_DISPUTE_STATUSES: ReadonlySet<string> = new Set(['OPEN', 'UNDER_REVIEW'])

/** Report states that still need a moderator decision. */
export const OPEN_REPORT_STATUSES: ReadonlySet<string> = new Set(['OPEN', 'REVIEWING'])

/**
 * Current page for a filtered list. The page snaps back to 1 whenever
 * `resetKey` (a serialisation of the active filters) changes. This uses the
 * "adjust state while rendering" pattern instead of an effect, so the first
 * request for new filters already asks for page 1.
 */
export function useFilteredPage(resetKey: string) {
  const [state, setState] = useState({ key: resetKey, page: 1 })
  if (state.key !== resetKey) setState({ key: resetKey, page: 1 })
  const page = state.key === resetKey ? state.page : 1
  const setPage = useCallback((next: number) => setState({ key: resetKey, page: next }), [resetKey])
  return [page, setPage] as const
}

/** Public bounty URL: slug when present, id otherwise (the route accepts both). */
export function bountyPath(bounty: { id: string; slug?: string | null }): string {
  return `/bounties/${encodeURIComponent(bounty.slug || bounty.id)}`
}

/** Pretty-printed JSON for metadata blocks; never throws. */
export function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

/** True for an ISO 8601 date-time string such as "2026-09-25T12:00:00Z". */
export function isIsoDateTime(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** "bounty.moderated.hide" → "Bounty moderated hide" */
export function humanizeAction(action: string): string {
  const s = action.replace(/[._]+/g, ' ').trim().toLowerCase()
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : action
}

/** Scrolls back to the top of the list after a page change (through the active smooth-scroll engine). */
export { scrollToTop } from '@/lib/scroll'
