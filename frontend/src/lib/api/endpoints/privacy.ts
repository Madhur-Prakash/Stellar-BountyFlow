import { API_BASE_URL, http, seg } from '../client'
import type {
  AdminDeletionParams,
  AdminDeletionRequest,
  AdminLegalVersion,
  DataExport,
  DeletionState,
  LegalStatus,
  LegalVersion,
  Page,
  PublishLegalVersionBody,
  RequestDeletionBody,
  ScreeningDecision,
  ScreeningDecisionParams,
  ScreeningEntry,
  ScreeningEntryParams,
  ScreeningStatus,
} from '../types'

/** The API returns download links as origin-relative paths (`/api/v1/…`); resolve them against the API origin. */
export function apiHref(path: string): string {
  return /^https?:\/\//i.test(API_BASE_URL) ? `${new URL(API_BASE_URL).origin}${path}` : path
}

export const privacyApi = {
  exports: () => http.get<DataExport[]>('/privacy/exports'),
  requestExport: () => http.post<DataExport>('/privacy/exports'),
  deletion: () => http.get<DeletionState>('/privacy/deletion'),
  requestDeletion: (body: RequestDeletionBody) => http.post<DeletionState>('/privacy/deletion', body),
  cancelDeletion: () => http.post<DeletionState>('/privacy/deletion/cancel'),
}

export const legalApi = {
  versions: () => http.get<LegalVersion[]>('/legal/versions'),
  status: () => http.get<LegalStatus>('/legal/status'),
  accept: (versionIds: string[]) => http.post<LegalStatus>('/legal/accept', { version_ids: versionIds }),
}

export const adminComplianceApi = {
  deletions: (params?: AdminDeletionParams) =>
    http.get<Page<AdminDeletionRequest>>('/admin/compliance/deletions', params),
  screeningStatus: () => http.get<ScreeningStatus>('/admin/compliance/screening/status'),
  screeningEntries: (params?: ScreeningEntryParams) =>
    http.get<Page<ScreeningEntry>>('/admin/compliance/screening/entries', params),
  addScreeningEntry: (body: { address: string; reason: string }) =>
    http.post<ScreeningEntry>('/admin/compliance/screening/entries', body),
  removeScreeningEntry: (id: string, note: string) =>
    http.post<ScreeningEntry>(`/admin/compliance/screening/entries/${seg(id)}/remove`, { note }),
  screeningDecisions: (params?: ScreeningDecisionParams) =>
    http.get<Page<ScreeningDecision>>('/admin/compliance/screening/decisions', params),
  legalVersions: () => http.get<AdminLegalVersion[]>('/admin/compliance/legal/versions'),
  publishLegalVersion: (body: PublishLegalVersionBody) =>
    http.post<AdminLegalVersion>('/admin/compliance/legal/versions', body),
  withdrawLegalVersion: (id: string) =>
    http.post<AdminLegalVersion>(`/admin/compliance/legal/versions/${seg(id)}/withdraw`),
}
