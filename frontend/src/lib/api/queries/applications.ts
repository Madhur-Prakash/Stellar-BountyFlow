import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { applicationsApi } from '../endpoints'
import type { ApplicationListParams, CreateApplicationRequest } from '../types'
import { qk } from './keys'

export function useMyApplications(params: ApplicationListParams = {}) {
  return useQuery({
    queryKey: qk.applications.mine(params),
    queryFn: () => applicationsApi.mine(params),
    placeholderData: keepPreviousData,
  })
}

export function useBountyApplications(bountyId: string | undefined, params: ApplicationListParams = {}) {
  return useQuery({
    queryKey: qk.bounties.applications(bountyId ?? '', params),
    queryFn: () => applicationsApi.listForBounty(bountyId!, params),
    enabled: !!bountyId,
    placeholderData: keepPreviousData,
  })
}

function useInvalidateApplications() {
  const client = useQueryClient()
  return () => {
    client.invalidateQueries({ queryKey: qk.applications.all })
    client.invalidateQueries({ queryKey: qk.bounties.all })
    client.invalidateQueries({ queryKey: qk.dashboard })
    client.invalidateQueries({ queryKey: qk.notifications.all })
  }
}

export function useApply(bountyId: string) {
  const invalidate = useInvalidateApplications()
  return useMutation({
    mutationFn: (body: CreateApplicationRequest) => applicationsApi.create(bountyId, body),
    onSuccess: invalidate,
  })
}

export function useWithdrawApplication() {
  const invalidate = useInvalidateApplications()
  return useMutation({ mutationFn: (id: string) => applicationsApi.withdraw(id), onSuccess: invalidate })
}

export function useAcceptApplication() {
  const invalidate = useInvalidateApplications()
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      applicationsApi.accept(id, note ? { note } : {}),
    onSuccess: invalidate,
  })
}

export function useRejectApplication() {
  const invalidate = useInvalidateApplications()
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      applicationsApi.reject(id, note ? { note } : {}),
    onSuccess: invalidate,
  })
}
