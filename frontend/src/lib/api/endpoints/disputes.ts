import { http, seg } from '../client'
import type {
  AddDisputeEvidenceRequest,
  CreateDisputeRequest,
  Dispute,
  ResolveDisputeRequest,
} from '../types'

export const disputesApi = {
  create: (bountyId: string, body: CreateDisputeRequest) =>
    http.post<Dispute>(`/bounties/${seg(bountyId)}/disputes`, body),
  mine: () => http.get<Dispute[]>('/disputes/me'),
  get: (id: string) => http.get<Dispute>(`/disputes/${seg(id)}`),
  addEvidence: (id: string, body: AddDisputeEvidenceRequest) =>
    http.post<Dispute>(`/disputes/${seg(id)}/evidence`, body),
  /** Moderator assigns self. */
  assign: (id: string) => http.post<Dispute>(`/disputes/${seg(id)}/assign`),
  resolve: (id: string, body: ResolveDisputeRequest) =>
    http.post<Dispute>(`/disputes/${seg(id)}/resolve`, body),
}
