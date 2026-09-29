import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { adminFeedbackApi, feedbackApi } from '../endpoints'
import type { AdminFeedbackParams, HandleFeedbackRequest, SubmitFeedbackRequest } from '../types'

import { qk } from './keys'

/** Sending feedback is fire and forget: nothing in the cache depends on it. */
export function useSubmitFeedback() {
  return useMutation({ mutationFn: (body: SubmitFeedbackRequest) => feedbackApi.submit(body) })
}

export function useAdminFeedback(params: AdminFeedbackParams = {}) {
  return useQuery({
    queryKey: qk.admin.feedback(params),
    queryFn: () => adminFeedbackApi.list(params),
    placeholderData: keepPreviousData,
  })
}

export function useHandleFeedback() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: HandleFeedbackRequest }) =>
      adminFeedbackApi.handle(id, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['admin', 'feedback'] }),
  })
}
