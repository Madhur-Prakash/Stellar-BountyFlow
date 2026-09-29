import { http, seg } from '../client'
import type {
  Attestation,
  AttestationDetail,
  CredentialRecord,
  IssuedCredential,
  IssuerInfo,
  MyAttestationCounts,
  Page,
  PageParams,
  ReputationSummary,
  VerifiableCredential,
  VerificationReport,
} from '../types'

export const reputationApi = {
  summary: (username: string) => http.get<ReputationSummary>(`/users/${seg(username)}/reputation`),
  attestations: (username: string, params?: PageParams) =>
    http.get<Page<Attestation>>(`/users/${seg(username)}/attestations`, params),
  attestation: (ref: string) => http.get<AttestationDetail>(`/attestations/${seg(ref)}`),
  myAttestations: (params?: PageParams) => http.get<Page<Attestation>>('/reputation/me/attestations', params),
  myCounts: () => http.get<MyAttestationCounts>('/reputation/me/counts'),
}

export const credentialsApi = {
  issuer: () => http.get<IssuerInfo>('/credentials/issuer'),
  mine: () => http.get<CredentialRecord[]>('/credentials/me'),
  get: (id: string) => http.get<IssuedCredential>(`/credentials/${seg(id)}`),
  issueCompletion: (attestationId: string) =>
    http.post<IssuedCredential>(`/credentials/completions/${seg(attestationId)}`),
  issueSummary: () => http.post<IssuedCredential>('/credentials/summary'),
  /** Public and side-effect free: anyone may check a credential, signed in or not. */
  verify: (credential: VerifiableCredential) =>
    http.post<VerificationReport>('/credentials/verify', { credential }),
}
