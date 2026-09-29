import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { githubApi } from '../endpoints'
import { qk } from './keys'

export function useGitHubConfig() {
  return useQuery({ queryKey: qk.github.config, queryFn: githubApi.config, staleTime: 5 * 60_000 })
}

export function useGitHubAccount(enabled = true) {
  return useQuery({ queryKey: qk.github.account, queryFn: githubApi.account, enabled })
}

export function usePublicGitHubAccount(username: string | undefined) {
  return useQuery({
    queryKey: qk.github.publicAccount(username ?? ''),
    queryFn: () => githubApi.publicAccount(username!),
    enabled: !!username,
  })
}

/** Linking or unlinking changes the verdict of the user's pull requests too. */
function useInvalidateGitHub() {
  const client = useQueryClient()
  return () => {
    client.invalidateQueries({ queryKey: qk.github.all })
    client.invalidateQueries({ queryKey: qk.submissions.all })
    client.invalidateQueries({ queryKey: qk.bounties.all })
  }
}

export function useGitHubChallenge() {
  return useMutation({ mutationFn: (login: string) => githubApi.challenge(login) })
}

export function useVerifyGist() {
  const invalidate = useInvalidateGitHub()
  return useMutation({ mutationFn: (gistUrl: string) => githubApi.verifyGist(gistUrl), onSuccess: invalidate })
}

export function useGitHubOAuthStart() {
  return useMutation({ mutationFn: githubApi.oauthStart })
}

export function useGitHubOAuthCallback() {
  const invalidate = useInvalidateGitHub()
  return useMutation({
    mutationFn: ({ code, state }: { code: string; state: string }) => githubApi.oauthCallback(code, state),
    onSuccess: invalidate,
  })
}

export function useUnlinkGitHub() {
  const invalidate = useInvalidateGitHub()
  return useMutation({ mutationFn: githubApi.unlink, onSuccess: invalidate })
}

function useInvalidatePullRequests() {
  const client = useQueryClient()
  return () => {
    client.invalidateQueries({ queryKey: qk.submissions.all })
    client.invalidateQueries({ queryKey: qk.bounties.all })
  }
}

export function useAddPullRequest(submissionId: string) {
  const invalidate = useInvalidatePullRequests()
  return useMutation({
    mutationFn: (url: string) => githubApi.addPullRequest(submissionId, url),
    onSuccess: invalidate,
  })
}

export function useRemovePullRequest(submissionId: string) {
  const invalidate = useInvalidatePullRequests()
  return useMutation({
    mutationFn: (pullRequestId: string) => githubApi.removePullRequest(submissionId, pullRequestId),
    onSuccess: invalidate,
  })
}

export function useRecheckPullRequests(submissionId: string) {
  const invalidate = useInvalidatePullRequests()
  return useMutation({ mutationFn: () => githubApi.recheck(submissionId), onSuccess: invalidate })
}
