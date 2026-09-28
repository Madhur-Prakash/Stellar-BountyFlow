import { http, seg } from '../client'
import type {
  Application,
  ApplicationListParams,
  CreateApplicationRequest,
  Page,
  ReviewApplicationRequest,
} from '../types'

export const applicationsApi = {
  create: (bountyId: string, body: CreateApplicationRequest) =>
    http.post<Application>(`/bounties/${seg(bountyId)}/applications`, body),
  listForBounty: (bountyId: string, params?: ApplicationListParams) =>
    http.get<Page<Application>>(`/bounties/${seg(bountyId)}/applications`, params),
  mine: (params?: ApplicationListParams) => http.get<Page<Application>>('/applications/me', params),
  withdraw: (id: string) => http.post<Application>(`/applications/${seg(id)}/withdraw`),
  accept: (id: string, body: ReviewApplicationRequest = {}) =>
    http.post<Application>(`/applications/${seg(id)}/accept`, body),
  reject: (id: string, body: ReviewApplicationRequest = {}) =>
    http.post<Application>(`/applications/${seg(id)}/reject`, body),
}
