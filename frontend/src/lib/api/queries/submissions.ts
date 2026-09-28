import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { submissionsApi } from '../endpoints'
import type {
  CreateSubmissionRequest,
  PageParams,
  SubmissionListParams,
  UpdateSubmissionRequest,
} from '../types'
import { qk } from './keys'

export function useMySubmissions(params: SubmissionListParams = {}) {
  return useQuery({
    queryKey: qk.submissions.mine(params),
    queryFn: () => submissionsApi.mine(params),
    placeholderData: keepPreviousData,
  })
}

export function useBountySubmissions(bountyId: string | undefined, params: PageParams = {}) {
  return useQuery({
    queryKey: qk.bounties.submissions(bountyId ?? '', params),
    queryFn: () => submissionsApi.listForBounty(bountyId!, params),
    enabled: !!bountyId,
    placeholderData: keepPreviousData,
  })
}

export function useSubmission(id: string | undefined) {
  return useQuery({
    queryKey: qk.submissions.detail(id ?? ''),
    queryFn: () => submissionsApi.get(id!),
    enabled: !!id,
  })
}

function useInvalidateSubmissions() {
  const client = useQueryClient()
  return () => {
    client.invalidateQueries({ queryKey: qk.submissions.all })
    client.invalidateQueries({ queryKey: qk.bounties.all })
    client.invalidateQueries({ queryKey: qk.payments.all })
    client.invalidateQueries({ queryKey: qk.dashboard })
    client.invalidateQueries({ queryKey: qk.notifications.all })
  }
}

export function useCreateSubmission(bountyId: string) {
  const invalidate = useInvalidateSubmissions()
  return useMutation({
    mutationFn: (body: CreateSubmissionRequest) => submissionsApi.create(bountyId, body),
    onSuccess: invalidate,
  })
}

export function useUpdateSubmission() {
  const invalidate = useInvalidateSubmissions()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateSubmissionRequest }) =>
      submissionsApi.update(id, body),
    onSuccess: invalidate,
  })
}

export function useRequestRevision() {
  const invalidate = useInvalidateSubmissions()
  return useMutation({
    mutationFn: ({ id, feedback }: { id: string; feedback: string }) =>
      submissionsApi.requestRevision(id, { feedback }),
    onSuccess: invalidate,
  })
}

export function useApproveSubmission() {
  const invalidate = useInvalidateSubmissions()
  return useMutation({
    mutationFn: ({ id, feedback }: { id: string; feedback?: string }) =>
      submissionsApi.approve(id, feedback ? { feedback } : {}),
    onSuccess: invalidate,
  })
}

export function useRejectSubmission() {
  const invalidate = useInvalidateSubmissions()
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => submissionsApi.reject(id, { reason }),
    onSuccess: invalidate,
  })
}
