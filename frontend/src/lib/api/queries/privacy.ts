import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { adminComplianceApi, legalApi, privacyApi } from '../endpoints'
import type {
  AdminDeletionParams,
  DataExport,
  PublishLegalVersionBody,
  RequestDeletionBody,
  ScreeningDecisionParams,
  ScreeningEntryParams,
} from '../types'
import { qk } from './keys'

const building = (list: DataExport[] | undefined) =>
  !!list?.some((e) => e.status === 'PENDING' || e.status === 'PROCESSING')

/** The user's recent exports. Polls while one is being built; signed links are refreshed on every fetch. */
export function useDataExports() {
  return useQuery({
    queryKey: qk.privacy.exports,
    queryFn: () => privacyApi.exports(),
    refetchInterval: (q) => (building(q.state.data) ? 3_000 : false),
  })
}

export function useRequestDataExport() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => privacyApi.requestExport(),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.privacy.exports }),
  })
}

export function useDeletionState() {
  return useQuery({ queryKey: qk.privacy.deletion, queryFn: () => privacyApi.deletion() })
}

export function useRequestDeletion() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: RequestDeletionBody) => privacyApi.requestDeletion(body),
    onSuccess: (state) => client.setQueryData(qk.privacy.deletion, state),
  })
}

export function useCancelDeletion() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => privacyApi.cancelDeletion(),
    onSuccess: (state) => client.setQueryData(qk.privacy.deletion, state),
  })
}

/** Which terms and privacy notice versions the signed-in user has accepted (gates the workspace). */
export function useLegalStatus(enabled = true) {
  return useQuery({
    queryKey: qk.legal.status,
    queryFn: () => legalApi.status(),
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useAcceptLegal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (versionIds: string[]) => legalApi.accept(versionIds),
    onSuccess: (status) => client.setQueryData(qk.legal.status, status),
  })
}

// ---------------------------------------------------------------------------
// Staff
// ---------------------------------------------------------------------------

export function useAdminDeletions(params: AdminDeletionParams = {}) {
  return useQuery({
    queryKey: qk.compliance.deletions(params),
    queryFn: () => adminComplianceApi.deletions(params),
    placeholderData: keepPreviousData,
  })
}

export function useScreeningStatus() {
  return useQuery({
    queryKey: qk.compliance.screeningStatus,
    queryFn: () => adminComplianceApi.screeningStatus(),
  })
}

export function useScreeningEntries(params: ScreeningEntryParams = {}) {
  return useQuery({
    queryKey: qk.compliance.screeningEntries(params),
    queryFn: () => adminComplianceApi.screeningEntries(params),
    placeholderData: keepPreviousData,
  })
}

export function useScreeningDecisions(params: ScreeningDecisionParams = {}) {
  return useQuery({
    queryKey: qk.compliance.screeningDecisions(params),
    queryFn: () => adminComplianceApi.screeningDecisions(params),
    placeholderData: keepPreviousData,
  })
}

function useInvalidateScreening() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: [...qk.compliance.all, 'screening'] })
}

export function useAddScreeningEntry() {
  const invalidate = useInvalidateScreening()
  return useMutation({
    mutationFn: (body: { address: string; reason: string }) => adminComplianceApi.addScreeningEntry(body),
    onSuccess: invalidate,
  })
}

export function useRemoveScreeningEntry() {
  const invalidate = useInvalidateScreening()
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      adminComplianceApi.removeScreeningEntry(id, note),
    onSuccess: invalidate,
  })
}

export function useAdminLegalVersions() {
  return useQuery({
    queryKey: qk.compliance.legalVersions,
    queryFn: () => adminComplianceApi.legalVersions(),
  })
}

export function usePublishLegalVersion() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: PublishLegalVersionBody) => adminComplianceApi.publishLegalVersion(body),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: qk.compliance.legalVersions }),
        client.invalidateQueries({ queryKey: qk.legal.all }),
      ]),
  })
}

export function useWithdrawLegalVersion() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => adminComplianceApi.withdrawLegalVersion(id),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: qk.compliance.legalVersions }),
        client.invalidateQueries({ queryKey: qk.legal.all }),
      ]),
  })
}
