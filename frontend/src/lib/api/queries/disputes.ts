import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { disputesApi } from '../endpoints'
import type { AddDisputeEvidenceRequest, CreateDisputeRequest, ResolveDisputeRequest } from '../types'
import { qk } from './keys'

export function useMyDisputes(enabled = true) {
  return useQuery({ queryKey: qk.disputes.mine, queryFn: () => disputesApi.mine(), enabled })
}

export function useDispute(id: string | undefined) {
  return useQuery({
    queryKey: qk.disputes.detail(id ?? ''),
    queryFn: () => disputesApi.get(id!),
    enabled: !!id,
  })
}

function useInvalidateDisputes() {
  const client = useQueryClient()
  return () => {
    client.invalidateQueries({ queryKey: qk.disputes.all })
    client.invalidateQueries({ queryKey: qk.admin.all })
    client.invalidateQueries({ queryKey: qk.bounties.all })
    client.invalidateQueries({ queryKey: qk.notifications.all })
  }
}

export function useRaiseDispute(bountyId: string) {
  const invalidate = useInvalidateDisputes()
  return useMutation({
    mutationFn: (body: CreateDisputeRequest) => disputesApi.create(bountyId, body),
    onSuccess: invalidate,
  })
}

export function useAddDisputeEvidence() {
  const invalidate = useInvalidateDisputes()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AddDisputeEvidenceRequest }) =>
      disputesApi.addEvidence(id, body),
    onSuccess: invalidate,
  })
}

export function useAssignDispute() {
  const invalidate = useInvalidateDisputes()
  return useMutation({ mutationFn: (id: string) => disputesApi.assign(id), onSuccess: invalidate })
}

export function useResolveDispute() {
  const invalidate = useInvalidateDisputes()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ResolveDisputeRequest }) => disputesApi.resolve(id, body),
    onSuccess: invalidate,
  })
}
