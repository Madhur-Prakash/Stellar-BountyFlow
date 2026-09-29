import { LoaderCircle, Plus, ScrollText, UserX } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage, isApiError } from '@/lib/api/client'
import {
  useAdminDeletions,
  useAdminLegalVersions,
  useMe,
  usePublishLegalVersion,
  useWithdrawLegalVersion,
} from '@/lib/api/queries'
import {
  DELETION_STATUSES,
  LEGAL_DOCUMENTS,
  type AdminDeletionRequest,
  type AdminLegalVersion,
  type DeletionStatus,
  type LegalDocument,
} from '@/lib/api/types'
import { formatDateTime, formatNumber } from '@/lib/format'
import { hasPermission } from '@/lib/permissions'

import {
  AdminTable,
  ClampedText,
  DateCell,
  FilterSelect,
  PagedResults,
  UserCell,
  type AdminColumn,
} from './admin-shared'
import { ADMIN_PAGE_SIZE, scrollToTop, useFilteredPage } from './admin-utils'

const DELETION_LABELS: Record<DeletionStatus, string> = {
  SCHEDULED: 'Scheduled',
  CANCELLED: 'Cancelled',
  COMPLETED: 'Deleted',
}
const DOCUMENT_LABELS: Record<LegalDocument, string> = { TERMS: 'Terms', PRIVACY: 'Privacy notice' }

type VersionState = 'scheduled' | 'current' | 'superseded' | 'withdrawn'
const STATE_BADGE: Record<
  VersionState,
  { label: string; variant: 'info' | 'warning' | 'muted' | 'outline' }
> = {
  scheduled: { label: 'Scheduled', variant: 'warning' },
  current: { label: 'In effect', variant: 'info' },
  superseded: { label: 'Superseded', variant: 'muted' },
  withdrawn: { label: 'Withdrawn', variant: 'outline' },
}

/** In effect, scheduled, superseded or withdrawn, from the list of all versions (newest first). */
function versionStates(versions: AdminLegalVersion[], now = Date.now()): Map<string, VersionState> {
  const states = new Map<string, VersionState>()
  const seenCurrent = new Set<LegalDocument>()
  for (const v of versions) {
    if (v.withdrawn_at) states.set(v.id, 'withdrawn')
    else if (Date.parse(v.effective_at) > now) states.set(v.id, 'scheduled')
    else if (!seenCurrent.has(v.document)) {
      seenCurrent.add(v.document)
      states.set(v.id, 'current')
    } else states.set(v.id, 'superseded')
  }
  return states
}

function DeletionsCard() {
  const [status, setStatus] = useState<DeletionStatus | undefined>('SCHEDULED')
  const [page, setPage] = useFilteredPage(status ?? '')
  const query = useAdminDeletions({ status, page, page_size: ADMIN_PAGE_SIZE })
  const columns: AdminColumn<AdminDeletionRequest>[] = [
    {
      key: 'user',
      header: 'Account',
      mobile: 'title',
      cell: (r) => (
        <span className="inline-flex min-w-0 flex-col">
          <UserCell user={r.user} avatar={false} />
          {r.status !== 'COMPLETED' && (
            <span className="truncate text-xs text-muted-foreground">{r.email}</span>
          )}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      mobile: 'aside',
      cell: (r) => (
        <Badge variant={r.status === 'SCHEDULED' ? 'warning' : 'muted'}>{DELETION_LABELS[r.status]}</Badge>
      ),
    },
    { key: 'requested', header: 'Requested', cell: (r) => <DateCell iso={r.created_at} /> },
    {
      key: 'scheduled',
      header: 'Deletes on',
      cell: (r) => <DateCell iso={r.status === 'COMPLETED' ? r.completed_at : r.scheduled_for} />,
    },
    {
      key: 'blockers',
      header: 'Blocked by',
      wide: true,
      cell: (r) =>
        r.blockers.length > 0 ? (
          <ClampedText text={r.blockers.map((b) => b.message).join(' ')} className="lg:min-w-48" />
        ) : r.pseudonym ? (
          <span className="font-mono text-xs text-muted-foreground">{r.pseudonym}</span>
        ) : (
          <span className="text-muted-foreground">Nothing</span>
        ),
    },
    {
      key: 'reason',
      header: 'Reason given',
      wide: true,
      desktopHidden: true,
      cell: (r) => <ClampedText text={r.reason} className="text-muted-foreground" />,
    },
  ]
  return (
    <section aria-labelledby="deletions-h" className="space-y-3">
      <h2 id="deletions-h" className="text-[0.9375rem] font-semibold">
        Account deletion requests
      </h2>
      <PagedResults
        query={query}
        skeleton="admin-privacy-deletions"
        label="Account deletion requests"
        itemLabel="requests"
        errorTitle="Could not load deletion requests"
        empty={{
          icon: UserX,
          title: status === 'SCHEDULED' ? 'No pending deletions' : 'No deletion requests',
        }}
        filtered={status !== 'SCHEDULED' && !!status}
        onClearFilters={() => setStatus('SCHEDULED')}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <FilterSelect
            id="admin-deletions-status"
            label="Filter by status"
            value={status}
            onChange={setStatus}
            options={DELETION_STATUSES}
            labels={DELETION_LABELS}
            allLabel="All requests"
          />
        }
      >
        {(items) => (
          <AdminTable
            rows={items}
            columns={columns}
            getKey={(r) => r.id}
            caption="Account deletion requests"
          />
        )}
      </PagedResults>
    </section>
  )
}

function PublishDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const publish = usePublishLegalVersion()
  const docId = useId()
  const versionId = useId()
  const summaryId = useId()
  const dateId = useId()
  const [document, setDocument] = useState<LegalDocument>('TERMS')
  const [version, setVersion] = useState('')
  const [summary, setSummary] = useState('')
  const [effective, setEffective] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const close = (next: boolean) => {
    if (!next) {
      setVersion('')
      setSummary('')
      setEffective('')
      setErrors({})
    }
    onOpenChange(next)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (!/^[A-Za-z0-9._-]{1,32}$/.test(version.trim())) next.version = 'Use letters, numbers, dots or dashes.'
    if (summary.trim().length < 10) next.summary = 'Summarise what changed (at least 10 characters).'
    setErrors(next)
    if (Object.keys(next).length) return
    publish.mutate(
      {
        document,
        version: version.trim(),
        summary: summary.trim(),
        effective_at: effective ? new Date(effective).toISOString() : undefined,
      },
      {
        onSuccess: (v) => {
          toast.success(
            Date.parse(v.effective_at) > Date.now()
              ? `Version ${v.version} is scheduled. Users are told in advance.`
              : `Version ${v.version} is in effect. Users accept it before continuing.`,
          )
          close(false)
        },
        onError: (err) => {
          if (isApiError(err) && Object.keys(err.fieldErrors).length) setErrors(err.fieldErrors)
          else toast.error(errorMessage(err))
        },
      },
    )
  }

  const describedBy = (id: string, key: string) => (errors[key] ? `${id}-error` : undefined)
  const fieldError = (id: string, key: string) =>
    errors[key] ? (
      <p id={`${id}-error`} className="text-[0.8125rem] text-destructive">
        {errors[key]}
      </p>
    ) : null

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Publish a new version</DialogTitle>
            <DialogDescription>
              Publish after the document text on the site is updated. A future date announces the change
              first.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor={docId}>Document</Label>
              <Select value={document} onValueChange={(v) => setDocument(v as LegalDocument)}>
                <SelectTrigger id={docId} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LEGAL_DOCUMENTS.map((d) => (
                    <SelectItem key={d} value={d}>
                      {DOCUMENT_LABELS[d]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor={versionId}>Version</Label>
              <Input
                id={versionId}
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="2026-10"
                maxLength={32}
                autoComplete="off"
                aria-invalid={!!errors.version}
                aria-describedby={describedBy(versionId, 'version')}
              />
              {fieldError(versionId, 'version')}
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor={summaryId}>What changed</Label>
              <Textarea
                id={summaryId}
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                maxLength={2000}
                rows={4}
                aria-invalid={!!errors.summary}
                aria-describedby={describedBy(summaryId, 'summary')}
              />
              {fieldError(summaryId, 'summary')}
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor={dateId}>
                Takes effect <span className="font-normal text-muted-foreground">(empty for now)</span>
              </Label>
              <Input
                id={dateId}
                type="datetime-local"
                value={effective}
                onChange={(e) => setEffective(e.target.value)}
                aria-invalid={!!errors.effective_at}
                aria-describedby={describedBy(dateId, 'effective_at')}
              />
              {fieldError(dateId, 'effective_at')}
            </div>
          </div>
          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={publish.isPending}>
              {publish.isPending && <LoaderCircle className="animate-spin" />}
              Publish version
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function LegalVersionsCard({ canManage }: { canManage: boolean }) {
  const query = useAdminLegalVersions()
  const withdraw = useWithdrawLegalVersion()
  const [publishing, setPublishing] = useState(false)
  const states = versionStates(query.data ?? [])
  const columns: AdminColumn<AdminLegalVersion>[] = [
    {
      key: 'document',
      header: 'Document',
      mobile: 'title',
      cell: (v) => (
        <span className="font-medium">
          {DOCUMENT_LABELS[v.document]}{' '}
          <span className="font-mono text-xs text-muted-foreground">{v.version}</span>
        </span>
      ),
    },
    {
      key: 'state',
      header: 'Status',
      mobile: 'aside',
      cell: (v) => {
        const b = STATE_BADGE[states.get(v.id) ?? 'superseded']
        return <Badge variant={b.variant}>{b.label}</Badge>
      },
    },
    {
      key: 'effective',
      header: 'Effective',
      cell: (v) => (
        <time dateTime={v.effective_at} className="whitespace-nowrap text-muted-foreground">
          {formatDateTime(v.effective_at)}
        </time>
      ),
    },
    { key: 'summary', header: 'What changed', wide: true, cell: (v) => <ClampedText text={v.summary} /> },
    {
      key: 'accepted',
      header: 'Accepted by',
      className: 'text-right',
      cell: (v) => <span className="amount">{formatNumber(v.accepted_count)}</span>,
    },
  ]
  if (canManage) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      hideHeader: true,
      className: 'text-right',
      mobile: 'actions',
      cell: (v) =>
        states.get(v.id) === 'scheduled' ? (
          <Button
            variant="outline"
            size="sm"
            disabled={withdraw.isPending}
            aria-label={`Withdraw ${DOCUMENT_LABELS[v.document]} ${v.version}`}
            onClick={() =>
              withdraw.mutate(v.id, {
                onSuccess: () => toast.success(`Version ${v.version} withdrawn.`),
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            Withdraw
          </Button>
        ) : null,
    })
  }
  return (
    <section aria-labelledby="legal-h">
      <Card className="gap-0 py-0">
        <CardHeader className="flex flex-row items-start justify-between gap-4 border-b py-4">
          <div>
            <CardTitle>
              <h2 id="legal-h">Terms and privacy versions</h2>
            </CardTitle>
            <CardDescription className="mt-1">
              Users accept a version before they continue once it is in effect.
            </CardDescription>
          </div>
          {canManage && (
            <Button size="sm" onClick={() => setPublishing(true)}>
              <Plus /> Publish version
            </Button>
          )}
        </CardHeader>
        {query.isError ? (
          <ErrorState
            error={query.error}
            title="Could not load versions"
            onRetry={() => query.refetch()}
            className="m-4"
          />
        ) : query.data && query.data.length === 0 ? (
          <EmptyState
            icon={ScrollText}
            title="No versions published"
            className="rounded-none border-0 bg-transparent py-14"
          />
        ) : (
          <Bones name="admin-privacy-legal" loading={query.isPending} fallback={<div className="h-40" />}>
            {query.data ? (
              <AdminTable
                rows={query.data}
                columns={columns}
                getKey={(v) => v.id}
                caption="Legal document versions"
              />
            ) : null}
          </Bones>
        )}
      </Card>
      <PublishDialog open={publishing} onOpenChange={setPublishing} />
    </section>
  )
}

export default function AdminPrivacyPage() {
  const { data: me } = useMe()
  const canManage = hasPermission(me, 'user:manage')
  return (
    <div className="space-y-8">
      <PageHeader
        title="Privacy and legal"
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Privacy and legal' }]}
        className="pb-0 lg:pb-0"
      />
      <DeletionsCard />
      <LegalVersionsCard canManage={canManage} />
    </div>
  )
}
