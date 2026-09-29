import { http, seg } from '../client'
import type {
  BountyListParams,
  CreateSavedSearchRequest,
  RecommendationPage,
  RelatedSkills,
  SavedSearch,
  UnsubscribeResult,
  UpdateSavedSearchRequest,
} from '../types'
import { bountyListQuery } from './bounties'

export const savedSearchesApi = {
  list: () => http.get<SavedSearch[]>('/saved-searches'),
  get: (id: string) => http.get<SavedSearch>(`/saved-searches/${seg(id)}`),
  create: (body: CreateSavedSearchRequest) => http.post<SavedSearch>('/saved-searches', body),
  update: (id: string, body: UpdateSavedSearchRequest) =>
    http.patch<SavedSearch>(`/saved-searches/${seg(id)}`, body),
  remove: (id: string) => http.delete<void>(`/saved-searches/${seg(id)}`),
  /** Resets "new since you last looked" (called when the search is opened in the marketplace). */
  markViewed: (id: string) => http.post<SavedSearch>(`/saved-searches/${seg(id)}/viewed`),
  /** Public: authorised by the signed token from an alert email. */
  unsubscribe: (token: string) => http.post<UnsubscribeResult>('/saved-searches/unsubscribe', { token }),
}

export const recommendationsApi = {
  /** Skill-graph recommendations for the signed-in user, narrowed by the marketplace filters (no sort). */
  list: (params: BountyListParams = {}) =>
    http.get<RecommendationPage>('/recommendations', bountyListQuery({ ...params, sort: undefined })),
}

export const skillsApi = {
  related: (skills: string[], limit = 8) => http.get<RelatedSkills>('/skills/related', { skills, limit }),
}
