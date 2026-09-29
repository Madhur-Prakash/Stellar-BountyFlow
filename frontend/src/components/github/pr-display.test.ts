import { describe, expect, it } from 'vitest'

import type { PullRequest } from '@/lib/api/types'

import { checksLabel, isPullRequestUrl, prLabel, qualifiesForMergeRequirement, verificationDetail } from './pr-display'

function pr(overrides: Partial<PullRequest> = {}): PullRequest {
  return {
    id: 'a0f1',
    url: 'https://github.com/stellar/js-stellar-sdk/pull/1744',
    repository: 'stellar/js-stellar-sdk',
    number: 1744,
    verification: 'VERIFIED',
    detail: null,
    state: 'MERGED',
    title: 'fix(contract): forward wallet signerAddress',
    author_login: 'Ryang-21',
    merged_at: '2026-09-24T22:25:15Z',
    head_sha: 'e472ff276862e95de544a704339f651447d99edb',
    draft: false,
    checks: 'SUCCESS',
    checks_passed: 18,
    checks_failed: 0,
    checks_pending: 0,
    check_runs: [],
    statuses: [],
    last_checked_at: '2026-09-29T10:00:00Z',
    next_check_at: null,
    ...overrides,
  }
}

describe('pull request URLs', () => {
  it.each([
    'https://github.com/stellar/js-stellar-sdk/pull/1744',
    'https://github.com/stellar/js-stellar-sdk/pull/1744/files',
    'http://www.github.com/a/b/pull/1',
  ])('accepts %s', (url) => {
    expect(isPullRequestUrl(url)).toBe(true)
  })

  it.each([
    'https://github.com/stellar/js-stellar-sdk/issues/1744',
    'https://gitlab.com/a/b/pull/1',
    'https://github.com/a/b/pull/abc',
    'not a url',
    '',
  ])('rejects %s', (url) => {
    expect(isPullRequestUrl(url)).toBe(false)
  })
})

describe('pull request display', () => {
  it('labels a pull request as owner/repo#number', () => {
    expect(prLabel(pr())).toBe('stellar/js-stellar-sdk#1744')
  })

  it('summarises checks, singular and plural', () => {
    expect(checksLabel(pr())).toBe('18 checks passed')
    expect(checksLabel(pr({ checks: 'SUCCESS', checks_passed: 1 }))).toBe('1 check passed')
    expect(checksLabel(pr({ checks: 'FAILURE', checks_failed: 2 }))).toBe('2 checks failing')
    expect(checksLabel(pr({ checks: 'PENDING', checks_pending: 3 }))).toBe('3 checks running')
    expect(checksLabel(pr({ checks: 'NONE' }))).toBe('No checks')
    expect(checksLabel(pr({ checks: null }))).toBeNull()
  })

  it('shows the API’s reason, and explains a pending check itself', () => {
    expect(verificationDetail(pr({ verification: 'AUTHOR_MISMATCH', detail: 'Opened by @someone.' }))).toBe(
      'Opened by @someone.',
    )
    expect(verificationDetail(pr({ verification: 'PENDING', detail: null }))).toBe(
      'BountyFlow checks this pull request with GitHub shortly.',
    )
    expect(verificationDetail(pr())).toBeNull()
  })

  it('only a verified, merged pull request satisfies a merged-PR requirement', () => {
    expect(qualifiesForMergeRequirement(pr())).toBe(true)
    expect(qualifiesForMergeRequirement(pr({ state: 'OPEN' }))).toBe(false)
    expect(qualifiesForMergeRequirement(pr({ state: 'CLOSED' }))).toBe(false)
    expect(qualifiesForMergeRequirement(pr({ verification: 'AUTHOR_MISMATCH' }))).toBe(false)
    expect(qualifiesForMergeRequirement(pr({ verification: 'REPO_MISMATCH' }))).toBe(false)
  })
})
