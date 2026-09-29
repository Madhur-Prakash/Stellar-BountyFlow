import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { credentialsApi, reputationApi } from '../endpoints'
import type { Attestation, PageParams, VerifiableCredential } from '../types'
import { qk } from './keys'

/** In-flight attestations settle on-chain within seconds; refresh while any is being recorded. */
const IN_FLIGHT: Attestation['status'][] = ['PENDING', 'SUBMITTED', 'REVOKING']

export function useReputationSummary(username: string | undefined) {
  return useQuery({
    queryKey: qk.reputation.summary(username ?? ''),
    queryFn: () => reputationApi.summary(username!),
    enabled: !!username,
  })
}

export function useUserAttestations(username: string | undefined, params: PageParams = {}) {
  return useQuery({
    queryKey: qk.reputation.attestations(username ?? '', params),
    queryFn: () => reputationApi.attestations(username!, params),
    enabled: !!username,
    placeholderData: keepPreviousData,
  })
}

export function useAttestation(ref: string | undefined) {
  return useQuery({
    queryKey: qk.reputation.attestation(ref ?? ''),
    queryFn: () => reputationApi.attestation(ref!),
    enabled: !!ref,
    retry: (count, error) => count < 2 && !(error as { status?: number }).status,
  })
}

export function useMyAttestations(params: PageParams = {}) {
  return useQuery({
    queryKey: qk.reputation.mine(params),
    queryFn: () => reputationApi.myAttestations(params),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((a) => IN_FLIGHT.includes(a.status)) ? 8_000 : false,
  })
}

export function useCredentialIssuer() {
  return useQuery({ queryKey: qk.credentials.issuer, queryFn: credentialsApi.issuer, staleTime: 5 * 60_000 })
}

export function useMyCredentials(enabled = true) {
  return useQuery({ queryKey: qk.credentials.mine, queryFn: credentialsApi.mine, enabled })
}

/** Saves a credential document as a JSON file. */
export function saveCredentialFile(document: VerifiableCredential, name: string) {
  const blob = new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = window.document.createElement('a')
  link.href = url
  link.download = name
  window.document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** Issues (or re-fetches the standing) credential for one attested completion, or the summary. */
export function useIssueCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (target: { attestationId: string } | 'summary') =>
      target === 'summary'
        ? credentialsApi.issueSummary()
        : credentialsApi.issueCompletion(target.attestationId),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.credentials.mine }),
  })
}

export function useVerifyCredential() {
  return useMutation({ mutationFn: (credential: VerifiableCredential) => credentialsApi.verify(credential) })
}
