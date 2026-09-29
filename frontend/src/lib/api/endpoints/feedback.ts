import { ensureCsrfToken, http, seg } from '../client'
import type {
  AdminFeedbackParams,
  Feedback,
  FeedbackPage,
  HandleFeedbackRequest,
  SubmitFeedbackRequest,
} from '../types'

export const feedbackApi = {
  /** Public: anyone may send a note. Signed-out visitors need a CSRF token first. */
  submit: async (body: SubmitFeedbackRequest) => {
    await ensureCsrfToken()
    return http.post<{ id: string }>('/feedback', body)
  },
}

export const adminFeedbackApi = {
  list: (params?: AdminFeedbackParams) => http.get<FeedbackPage>('/admin/feedback', params),
  handle: (id: string, body: HandleFeedbackRequest) =>
    http.post<Feedback>(`/admin/feedback/${seg(id)}/handle`, body),
}
