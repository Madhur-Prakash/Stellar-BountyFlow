import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { bountiesApi } from '../endpoints'
import type {
  BountyListParams,
  CreateBountyRequest,
  MyBountiesParams,
  PageParams,
  UpdateBountyRequest,
} from '../types'
import { qk } from './keys'

export function useBounties(params: BountyListParams = {}) {
  return useQuery({
    queryKey: qk.bounties.list(params),
    queryFn: () => bountiesApi.list(params),
    placeholderData: keepPreviousData,
  })
}

export function useFeaturedBounties() {
  return useQuery({
    queryKey: qk.bounties.featured,
    queryFn: () => bountiesApi.featured(),
    staleTime: 60_000,
  })
}

export function useMyBounties(params: MyBountiesParams = {}) {
  return useQuery({
    queryKey: qk.bounties.mine(params),
    queryFn: () => bountiesApi.mine(params),
    placeholderData: keepPreviousData,
  })
}

export function useSavedBounties(params: PageParams = {}) {
  return useQuery({
    queryKey: qk.bounties.saved(params),
    queryFn: () => bountiesApi.saved(params),
    placeholderData: keepPreviousData,
  })
}

export function useBounty(idOrSlug: string | undefined) {
  return useQuery({
    queryKey: qk.bounties.detail(idOrSlug ?? ''),
    queryFn: () => bountiesApi.get(idOrSlug!),
    enabled: !!idOrSlug,
  })
}

export function useBountyActivity(bountyId: string | undefined, params: PageParams = {}) {
  return useQuery({
    queryKey: qk.bounties.activity(bountyId ?? '', params),
    queryFn: () => bountiesApi.activity(bountyId!, params),
    enabled: !!bountyId,
    placeholderData: keepPreviousData,
  })
}

function useInvalidateBounties() {
  const client = useQueryClient()
  return () => {
    client.invalidateQueries({ queryKey: qk.bounties.all })
    client.invalidateQueries({ queryKey: qk.dashboard })
    client.invalidateQueries({ queryKey: qk.analytics.all })
  }
}

export function useCreateBounty() {
  const invalidate = useInvalidateBounties()
  return useMutation({
    mutationFn: (body: CreateBountyRequest) => bountiesApi.create(body),
    onSuccess: invalidate,
  })
}

export function useUpdateBounty(bountyId: string) {
  const invalidate = useInvalidateBounties()
  return useMutation({
    mutationFn: (body: UpdateBountyRequest) => bountiesApi.update(bountyId, body),
    onSuccess: invalidate,
  })
}

export function usePublishBounty() {
  const invalidate = useInvalidateBounties()
  return useMutation({
    mutationFn: (bountyId: string) => bountiesApi.publish(bountyId),
    onSuccess: invalidate,
  })
}

export function useCancelBounty() {
  const invalidate = useInvalidateBounties()
  return useMutation({
    mutationFn: ({ bountyId, reason }: { bountyId: string; reason: string }) =>
      bountiesApi.cancel(bountyId, { reason }),
    onSuccess: invalidate,
  })
}

export function useToggleBookmark() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ bountyId, bookmarked }: { bountyId: string; bookmarked: boolean }) =>
      bookmarked ? bountiesApi.unbookmark(bountyId) : bountiesApi.bookmark(bountyId),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.bounties.all }),
  })
}

export function useReportBounty() {
  return useMutation({
    mutationFn: ({ bountyId, reason }: { bountyId: string; reason: string }) =>
      bountiesApi.report(bountyId, { reason }),
  })
}

export function useFeatureBounty() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ bountyId, featured }: { bountyId: string; featured: boolean }) =>
      bountiesApi.feature(bountyId, { featured }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: qk.bounties.all })
      client.invalidateQueries({ queryKey: qk.admin.all })
    },
  })
}
