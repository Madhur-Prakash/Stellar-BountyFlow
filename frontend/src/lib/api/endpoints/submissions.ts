import { http, seg } from '../client'
import type {
  ApproveSubmissionRequest,
  CreateSubmissionRequest,
  Page,
  PageParams,
  RejectSubmissionRequest,
  RequestRevisionRequest,
  Submission,
  SubmissionListParams,
  UpdateSubmissionRequest,
} from '../types'

export const submissionsApi = {
  create: (bountyId: string, body: CreateSubmissionRequest) =>
    http.post<Submission>(`/bounties/${seg(bountyId)}/submissions`, body),
  listForBounty: (bountyId: string, params?: PageParams) =>
    http.get<Page<Submission>>(`/bounties/${seg(bountyId)}/submissions`, params),
  mine: (params?: SubmissionListParams) => http.get<Page<Submission>>('/submissions/me', params),
  get: (id: string) => http.get<Submission>(`/submissions/${seg(id)}`),
  update: (id: string, body: UpdateSubmissionRequest) =>
    http.patch<Submission>(`/submissions/${seg(id)}`, body),
  requestRevision: (id: string, body: RequestRevisionRequest) =>
    http.post<Submission>(`/submissions/${seg(id)}/request-revision`, body),
  approve: (id: string, body: ApproveSubmissionRequest = {}) =>
    http.post<Submission>(`/submissions/${seg(id)}/approve`, body),
  reject: (id: string, body: RejectSubmissionRequest) =>
    http.post<Submission>(`/submissions/${seg(id)}/reject`, body),
}
