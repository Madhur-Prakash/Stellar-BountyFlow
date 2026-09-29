import { http, seg } from '../client'
import type { GitHubAccount, GitHubChallenge, GitHubConfig, PublicGitHubAccount, PullRequest } from '../types'

/** GitHub account linking (gist proof, optional OAuth) and pull requests on submissions. */
export const githubApi = {
  config: () => http.get<GitHubConfig>('/github/config'),
  account: () => http.get<GitHubAccount | null>('/github/account'),
  challenge: (login: string) => http.post<GitHubChallenge>('/github/account/challenge', { login }),
  verifyGist: (gist_url: string) => http.post<GitHubAccount>('/github/account/verify-gist', { gist_url }),
  oauthStart: () => http.post<{ authorize_url: string }>('/github/oauth/start'),
  oauthCallback: (code: string, state: string) =>
    http.post<GitHubAccount>('/github/oauth/callback', { code, state }),
  unlink: () => http.delete<void>('/github/account'),
  publicAccount: (username: string) => http.get<PublicGitHubAccount | null>(`/users/${seg(username)}/github`),
  pullRequests: (submissionId: string) =>
    http.get<PullRequest[]>(`/submissions/${seg(submissionId)}/pull-requests`),
  addPullRequest: (submissionId: string, url: string) =>
    http.post<PullRequest>(`/submissions/${seg(submissionId)}/pull-requests`, { url }),
  removePullRequest: (submissionId: string, pullRequestId: string) =>
    http.delete<void>(`/submissions/${seg(submissionId)}/pull-requests/${seg(pullRequestId)}`),
  recheck: (submissionId: string) =>
    http.post<PullRequest[]>(`/submissions/${seg(submissionId)}/pull-requests/recheck`),
}
