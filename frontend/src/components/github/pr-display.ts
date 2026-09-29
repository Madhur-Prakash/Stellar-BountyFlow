import type { ChecksStatus, PullRequest, PullRequestState, PullRequestVerification } from '@/lib/api/types'

type Variant = 'info' | 'danger' | 'warning' | 'muted' | 'cyan' | 'outline'

export const VERIFICATION_LABELS: Record<PullRequestVerification, string> = {
  PENDING: 'Not checked yet',
  VERIFIED: 'Verified',
  NOT_FOUND: 'Not found',
  REPO_MISMATCH: 'Wrong repository',
  AUTHOR_MISMATCH: 'Author mismatch',
  AUTHOR_NOT_LINKED: 'Author not linked',
  UNAVAILABLE: 'GitHub unavailable',
}

export const VERIFICATION_VARIANTS: Record<PullRequestVerification, Variant> = {
  PENDING: 'muted',
  VERIFIED: 'info',
  NOT_FOUND: 'danger',
  REPO_MISMATCH: 'danger',
  AUTHOR_MISMATCH: 'danger',
  AUTHOR_NOT_LINKED: 'warning',
  UNAVAILABLE: 'warning',
}

export const STATE_LABELS: Record<PullRequestState, string> = {
  OPEN: 'Open',
  CLOSED: 'Closed',
  MERGED: 'Merged',
}

export const STATE_VARIANTS: Record<PullRequestState, Variant> = {
  OPEN: 'outline',
  CLOSED: 'muted',
  MERGED: 'cyan',
}

export function checksLabel(pr: Pick<PullRequest, 'checks' | 'checks_passed' | 'checks_failed' | 'checks_pending'>) {
  const labels: Record<ChecksStatus, string> = {
    SUCCESS: `${pr.checks_passed} check${pr.checks_passed === 1 ? '' : 's'} passed`,
    FAILURE: `${pr.checks_failed} check${pr.checks_failed === 1 ? '' : 's'} failing`,
    PENDING: `${pr.checks_pending} check${pr.checks_pending === 1 ? '' : 's'} running`,
    NONE: 'No checks',
  }
  return pr.checks ? labels[pr.checks] : null
}

/** Plain-words reason for a verdict other than "Verified", when the API gave none. */
export function verificationDetail(pr: PullRequest): string | null {
  if (pr.detail) return pr.detail
  if (pr.verification === 'PENDING') return 'BountyFlow checks this pull request with GitHub shortly.'
  return null
}

/** "owner/repo#123" */
export const prLabel = (pr: Pick<PullRequest, 'repository' | 'number'>) => `${pr.repository}#${pr.number}`

/** A merged pull request verified as the contributor's, which is what a "merged PR required" bounty needs. */
export const qualifiesForMergeRequirement = (pr: PullRequest) =>
  pr.verification === 'VERIFIED' && pr.state === 'MERGED'

const PR_URL = /^https?:\/\/(www\.)?github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+\/pull\/\d+(\/.*)?$/i

export const isPullRequestUrl = (value: string) => PR_URL.test(value.trim())
