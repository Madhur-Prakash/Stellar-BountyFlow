import { http, seg, type QueryParams } from '../client'
import type {
  ActivityItem,
  BountyDetail,
  BountyListParams,
  BountySummary,
  CancelBountyRequest,
  CreateBountyRequest,
  FeatureBountyRequest,
  MyBountiesParams,
  Page,
  PageParams,
  ReportBountyRequest,
  ReportCreatedResponse,
  UpdateBountyRequest,
} from '../types'

/** Serialises marketplace filters to the wire format (arrays → comma lists). */
export const bountyListQuery = (p: BountyListParams = {}): QueryParams => ({
  q: p.q,
  category: p.category,
  skills: p.skills,
  tags: p.tags,
  difficulty: p.difficulty,
  status: p.status,
  min_reward: p.min_reward,
  max_reward: p.max_reward,
  deadline_before: p.deadline_before,
  deadline_after: p.deadline_after,
  funded_only: p.funded_only ? true : undefined,
  sort: p.sort,
  page: p.page,
  page_size: p.page_size,
})

export const bountiesApi = {
  list: (params?: BountyListParams) => http.get<Page<BountySummary>>('/bounties', bountyListQuery(params)),
  featured: () => http.get<BountySummary[]>('/bounties/featured'),
  mine: (params?: MyBountiesParams) => http.get<Page<BountySummary>>('/bounties/mine', params),
  saved: (params?: PageParams) => http.get<Page<BountySummary>>('/bounties/saved', params),
  create: (body: CreateBountyRequest) => http.post<BountyDetail>('/bounties', body),
  get: (idOrSlug: string) => http.get<BountyDetail>(`/bounties/${seg(idOrSlug)}`),
  update: (bountyId: string, body: UpdateBountyRequest) =>
    http.patch<BountyDetail>(`/bounties/${seg(bountyId)}`, body),
  publish: (bountyId: string) => http.post<BountyDetail>(`/bounties/${seg(bountyId)}/publish`),
  cancel: (bountyId: string, body: CancelBountyRequest) =>
    http.post<BountyDetail>(`/bounties/${seg(bountyId)}/cancel`, body),
  bookmark: (bountyId: string) => http.post<void>(`/bounties/${seg(bountyId)}/bookmark`),
  unbookmark: (bountyId: string) => http.delete<void>(`/bounties/${seg(bountyId)}/bookmark`),
  report: (bountyId: string, body: ReportBountyRequest) =>
    http.post<ReportCreatedResponse>(`/bounties/${seg(bountyId)}/report`, body),
  activity: (bountyId: string, params?: PageParams) =>
    http.get<Page<ActivityItem>>(`/bounties/${seg(bountyId)}/activity`, params),
  feature: (bountyId: string, body: FeatureBountyRequest) =>
    http.post<BountyDetail>(`/bounties/${seg(bountyId)}/feature`, body),
}
