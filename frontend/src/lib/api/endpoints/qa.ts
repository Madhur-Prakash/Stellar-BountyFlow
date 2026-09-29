import { http, seg } from '../client'
import type {
  ModeratedPost,
  ModeratePostRequest,
  QAThread,
  QAVote,
  QuestionListParams,
  QuestionPage,
  ReportCreatedResponse,
} from '../types'

/** Bounty Q&A: public reads, signed-in writes, staff moderation. */
export const qaApi = {
  list: (bountyRef: string, params?: QuestionListParams) =>
    http.get<QuestionPage>(`/bounties/${seg(bountyRef)}/questions`, params),
  ask: (bountyId: string, body: string) =>
    http.post<QAThread>(`/bounties/${seg(bountyId)}/questions`, { body }),
  reply: (postId: string, body: string) => http.post<QAThread>(`/qa/posts/${seg(postId)}/replies`, { body }),
  edit: (postId: string, body: string) => http.patch<QAThread>(`/qa/posts/${seg(postId)}`, { body }),
  remove: (postId: string) => http.delete<void>(`/qa/posts/${seg(postId)}`),
  upvote: (postId: string) => http.put<QAVote>(`/qa/posts/${seg(postId)}/vote`),
  removeVote: (postId: string) => http.delete<QAVote>(`/qa/posts/${seg(postId)}/vote`),
  accept: (postId: string) => http.post<QAThread>(`/qa/posts/${seg(postId)}/accept`),
  unaccept: (postId: string) => http.delete<QAThread>(`/qa/posts/${seg(postId)}/accept`),
  pin: (postId: string) => http.post<QAThread>(`/qa/posts/${seg(postId)}/pin`),
  unpin: (postId: string) => http.delete<QAThread>(`/qa/posts/${seg(postId)}/pin`),
  report: (postId: string, reason: string) =>
    http.post<ReportCreatedResponse>(`/qa/posts/${seg(postId)}/report`, { reason }),
  moderate: (postId: string, body: ModeratePostRequest) =>
    http.post<ModeratedPost>(`/admin/qa/posts/${seg(postId)}/moderate`, body),
}
