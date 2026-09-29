import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { qaApi } from '../endpoints'
import type { ModeratePostRequest, QuestionListParams } from '../types'
import { qk } from './keys'

export function useQuestions(bountyRef: string | undefined, params: QuestionListParams = {}) {
  return useQuery({
    queryKey: qk.qa.threads(bountyRef ?? '', params),
    queryFn: () => qaApi.list(bountyRef!, params),
    enabled: !!bountyRef,
    placeholderData: keepPreviousData,
  })
}

/** Every Q&A change refreshes the threads and the bounty (its question count). */
function useInvalidateQA() {
  const client = useQueryClient()
  return () => {
    client.invalidateQueries({ queryKey: qk.qa.all })
    client.invalidateQueries({ queryKey: qk.bounties.all })
  }
}

export function useAskQuestion(bountyId: string) {
  const invalidate = useInvalidateQA()
  return useMutation({ mutationFn: (body: string) => qaApi.ask(bountyId, body), onSuccess: invalidate })
}

export function useReply() {
  const invalidate = useInvalidateQA()
  return useMutation({
    mutationFn: ({ postId, body }: { postId: string; body: string }) => qaApi.reply(postId, body),
    onSuccess: invalidate,
  })
}

export function useEditPost() {
  const invalidate = useInvalidateQA()
  return useMutation({
    mutationFn: ({ postId, body }: { postId: string; body: string }) => qaApi.edit(postId, body),
    onSuccess: invalidate,
  })
}

export function useDeletePost() {
  const invalidate = useInvalidateQA()
  return useMutation({ mutationFn: (postId: string) => qaApi.remove(postId), onSuccess: invalidate })
}

export function useVote() {
  const invalidate = useInvalidateQA()
  return useMutation({
    mutationFn: ({ postId, up }: { postId: string; up: boolean }) =>
      up ? qaApi.upvote(postId) : qaApi.removeVote(postId),
    onSuccess: invalidate,
  })
}

export function useAcceptAnswer() {
  const invalidate = useInvalidateQA()
  return useMutation({
    mutationFn: ({ postId, accepted }: { postId: string; accepted: boolean }) =>
      accepted ? qaApi.accept(postId) : qaApi.unaccept(postId),
    onSuccess: invalidate,
  })
}

export function usePinQuestion() {
  const invalidate = useInvalidateQA()
  return useMutation({
    mutationFn: ({ postId, pinned }: { postId: string; pinned: boolean }) =>
      pinned ? qaApi.pin(postId) : qaApi.unpin(postId),
    onSuccess: invalidate,
  })
}

export function useReportPost() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ postId, reason }: { postId: string; reason: string }) => qaApi.report(postId, reason),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.admin.all }),
  })
}

export function useModeratePost() {
  const client = useQueryClient()
  const invalidate = useInvalidateQA()
  return useMutation({
    mutationFn: ({ postId, body }: { postId: string; body: ModeratePostRequest }) =>
      qaApi.moderate(postId, body),
    onSuccess: () => {
      invalidate()
      client.invalidateQueries({ queryKey: qk.admin.all })
    },
  })
}
