/**
 * Collaboration: bounty Q&A and GitHub (account linking, pull requests on submissions). Mirrors docs/api.md
 * ("Questions" and "GitHub").
 */
import type { ISODateTime, Page, PageParams, UserSummary } from '../types'

// ---------------------------------------------------------------------------
// Q&A
// ---------------------------------------------------------------------------

export const QA_SORTS = ['newest', 'helpful'] as const
export type QASort = (typeof QA_SORTS)[number]

export const QUESTION_MIN = 10
export const REPLY_MIN = 2
export const QA_BODY_MAX = 5000

export type QAPost = {
  id: string
  /** The thread: a question's own id. */
  question_id: string
  parent_id: string | null
  /** null once deleted */
  author: UserSummary | null
  /** Markdown. null when deleted, or hidden and you are neither its author nor a moderator. */
  body: string | null
  /** Written by the bounty's requester. */
  is_requester: boolean
  is_mine: boolean
  is_pinned: boolean
  is_accepted: boolean
  upvotes: number
  viewer_voted: boolean
  is_deleted: boolean
  is_hidden: boolean
  /** Only for the author and moderators. */
  hidden_reason: string | null
  edited_at: ISODateTime | null
  created_at: ISODateTime
}

export type QAThread = QAPost & {
  replies: QAPost[]
  reply_count: number
  /** The requester replied, or a reply was accepted. */
  answered: boolean
}

export type QuestionPage = Page<QAThread> & {
  questions_count: number
  can_ask: boolean
  closed_reason: string | null
  viewer_is_requester: boolean
  viewer_is_moderator: boolean
}

export type QuestionListParams = PageParams & { sort?: QASort }
export type QAVote = { post_id: string; upvotes: number; viewer_voted: boolean }
export type ModeratedPost = QAPost & { bounty_id: string; bounty_slug: string }
export type ModeratePostRequest = { action: 'HIDE' | 'UNHIDE'; reason: string }

/** Context the moderation queue shows beside a reported Q&A post. */
export type ReportTargetSummary = {
  label: string
  excerpt: string | null
  link: string | null
  author: UserSummary | null
  is_hidden: boolean
  is_deleted: boolean
  bounty_id: string | null
}

// ---------------------------------------------------------------------------
// GitHub
// ---------------------------------------------------------------------------

export type GitHubConfig = { oauth_enabled: boolean; webhook_enabled: boolean; authenticated_api: boolean }

export type GitHubAccount = {
  github_id: number
  login: string
  avatar_url: string | null
  profile_url: string
  method: 'GIST' | 'OAUTH'
  proof_url: string | null
  verified_at: ISODateTime
}

export type PublicGitHubAccount = Pick<GitHubAccount, 'login' | 'avatar_url' | 'profile_url' | 'verified_at'>

export type GitHubChallenge = { login: string; challenge: string; filename: string; expires_at: ISODateTime }

export const PR_VERIFICATIONS = [
  'PENDING',
  'VERIFIED',
  'NOT_FOUND',
  'REPO_MISMATCH',
  'AUTHOR_MISMATCH',
  'AUTHOR_NOT_LINKED',
  'UNAVAILABLE',
] as const
export type PullRequestVerification = (typeof PR_VERIFICATIONS)[number]
export type PullRequestState = 'OPEN' | 'CLOSED' | 'MERGED'
export type ChecksStatus = 'SUCCESS' | 'FAILURE' | 'PENDING' | 'NONE'

export type PullRequest = {
  id: string
  url: string
  /** "owner/name" */
  repository: string
  number: number
  verification: PullRequestVerification
  /** Why it did not verify (or why GitHub could not be reached). */
  detail: string | null
  state: PullRequestState | null
  title: string | null
  author_login: string | null
  merged_at: ISODateTime | null
  head_sha: string | null
  draft: boolean
  checks: ChecksStatus | null
  checks_passed: number
  checks_failed: number
  checks_pending: number
  check_runs: { name: string | null; status: string | null; conclusion: string | null }[]
  statuses: { context: string | null; state: string | null }[]
  last_checked_at: ISODateTime | null
  next_check_at: ISODateTime | null
}

export const MAX_PULL_REQUESTS = 5
