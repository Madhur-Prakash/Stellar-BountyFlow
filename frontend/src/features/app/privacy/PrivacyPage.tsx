import { useQueryClient } from '@tanstack/react-query'
import { Download, FileJson, LoaderCircle, ShieldAlert, Trash2 } from 'lucide-react'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import { errorMessage, isApiError } from '@/lib/api/client'
import { apiHref, privacyApi } from '@/lib/api/endpoints'
import {
  qk,
  useCancelDeletion,
  useDataExports,
  useDeletionState,
  useLegalStatus,
  useRequestDataExport,
  useRequestDeletion,
} from '@/lib/api/queries'
import type { DataExport, DeletionState, ExportStatus, LegalDocument } from '@/lib/api/types'
import { formatDate, formatDateTime, formatRelative } from '@/lib/format'

import { AccountLayout } from '../AccountNav'
import { CardQuery } from '../workspace-ui'

const EXPORT_BADGE: Record<ExportStatus, { label: string; variant: 'muted' | 'info' | 'danger' }> = {
  PENDING: { label: 'Queued', variant: 'muted' },
  PROCESSING: { label: 'Preparing', variant: 'info' },
  READY: { label: 'Ready', variant: 'info' },
  FAILED: { label: 'Failed', variant: 'danger' },
  EXPIRED: { label: 'Expired', variant: 'muted' },
}

const DOCUMENTS: Record<LegalDocument, { label: string; path: string }> = {
  TERMS: { label: 'Terms of service', path: '/terms' },
  PRIVACY: { label: 'Privacy notice', path: '/privacy' },
}

function formatBytes(n: number | null): string {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string
  title: string
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-h`}>
      <Card className="gap-0 pb-0">
        <CardHeader className="pb-5">
          <CardTitle>
            <h2 id={`${id}-h`}>{title}</h2>
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        {children}
      </Card>
    </section>
  )
}

/** Fetches a fresh signed link (they last a few minutes) and hands it to the browser as a download. */
function useDownloadExport() {
  const client = useQueryClient()
  const [busy, setBusy] = useState<string | null>(null)
  const download = async (id: string) => {
    setBusy(id)
    try {
      const list = await client.fetchQuery({
        queryKey: qk.privacy.exports,
        queryFn: () => privacyApi.exports(),
        staleTime: 0,
      })
      const fresh = list.find((e) => e.id === id)
      if (!fresh?.download_url) {
        toast.error('This export is no longer available. Request a new one.')
        return
      }
      const link = document.createElement('a')
      link.href = apiHref(fresh.download_url)
      link.download = ''
      link.rel = 'noopener'
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  return { download, busy }
}

function ExportRow({
  item,
  onDownload,
  busy,
}: {
  item: DataExport
  onDownload: (id: string) => void
  busy: boolean
}) {
  const badge = EXPORT_BADGE[item.status]
  return (
    <li className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="flex min-w-0 items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border bg-surface text-muted-foreground">
          <FileJson className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">
              Requested{' '}
              <time dateTime={item.created_at} title={formatDateTime(item.created_at)}>
                {formatRelative(item.created_at)}
              </time>
            </span>
            <Badge variant={badge.variant}>{badge.label}</Badge>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {item.status === 'READY' && item.expires_at ? (
              <>
                {formatBytes(item.size_bytes)}, available until{' '}
                <time dateTime={item.expires_at}>{formatDateTime(item.expires_at)}</time>
              </>
            ) : item.status === 'PENDING' || item.status === 'PROCESSING' ? (
              'We’ll email you when it’s ready.'
            ) : item.status === 'FAILED' ? (
              'Something went wrong while preparing it. Request a new export.'
            ) : (
              'The file was deleted when it expired.'
            )}
          </p>
        </div>
      </div>
      {item.status === 'READY' && (
        <Button
          variant="outline"
          className="shrink-0 self-start sm:self-auto"
          onClick={() => onDownload(item.id)}
          disabled={busy}
        >
          {busy ? <LoaderCircle className="animate-spin" /> : <Download />}
          Download
        </Button>
      )}
    </li>
  )
}

function ExportCard() {
  const query = useDataExports()
  const request = useRequestDataExport()
  const { download, busy } = useDownloadExport()
  const building = query.data?.some((e) => e.status === 'PENDING' || e.status === 'PROCESSING') ?? false
  return (
    <Section
      id="export"
      title="Your data"
      description="Get a copy of everything BountyFlow holds about your account as a JSON file: profile, bounties, applications, submissions, payments, wallets, notifications and account activity."
    >
      <div className="flex flex-wrap items-center gap-3 border-t px-5 py-4">
        <Button
          onClick={() =>
            request.mutate(undefined, {
              onSuccess: () => toast.success('Export requested. We’ll email you when it’s ready.'),
              onError: (e) => toast.error(errorMessage(e)),
            })
          }
          disabled={request.isPending || building}
        >
          {request.isPending ? <LoaderCircle className="animate-spin" /> : <Download />}
          Request export
        </Button>
        <p className="text-[0.8125rem] text-muted-foreground">
          Download links work only while you’re signed in.
        </p>
      </div>
      <div className="border-t">
        <CardQuery
          query={query}
          skeleton="app-privacy-exports"
          rows={2}
          isEmpty={(d) => d.length === 0}
          empty={{ icon: FileJson, title: 'No exports yet' }}
        >
          {(items) => (
            <ul className="divide-y" aria-label="Data exports">
              {items.map((item) => (
                <ExportRow key={item.id} item={item} onDownload={download} busy={busy === item.id} />
              ))}
            </ul>
          )}
        </CardQuery>
      </div>
    </Section>
  )
}

function LegalCard() {
  const query = useLegalStatus()
  return (
    <Section id="legal" title="Terms and privacy">
      <div className="border-t">
        <CardQuery query={query} skeleton="app-privacy-legal" rows={2}>
          {(status) => (
            <ul className="divide-y">
              {status.documents.map((d) => {
                const doc = DOCUMENTS[d.document]
                return (
                  <li
                    key={d.document}
                    className="flex items-center justify-between gap-4 px-4 py-3.5 sm:px-5"
                  >
                    <div className="min-w-0 text-sm">
                      <div className="font-medium">{doc.label}</div>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {!d.current
                          ? 'No version published yet.'
                          : `Version ${d.current.version}, ${
                              d.accepted_at
                                ? `accepted ${formatDate(d.accepted_at)}`
                                : d.accepted_current
                                  ? 'accepted when you signed up'
                                  : 'not accepted yet'
                            }`}
                        {d.upcoming &&
                          `. Version ${d.upcoming.version} takes effect ${formatDate(d.upcoming.effective_at)}${
                            d.accepted_upcoming ? ' (accepted)' : ''
                          }`}
                      </p>
                    </div>
                    <Button asChild variant="ghost" size="sm" className="shrink-0">
                      <Link to={doc.path} target="_blank" rel="noopener">
                        Read<span className="sr-only"> the {doc.label.toLowerCase()}</span>
                      </Link>
                    </Button>
                  </li>
                )
              })}
            </ul>
          )}
        </CardQuery>
      </div>
    </Section>
  )
}

function DeleteDialog({
  open,
  onOpenChange,
  graceDays,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  graceDays: number
}) {
  const request = useRequestDeletion()
  const passwordId = useId()
  const reasonId = useId()
  const [password, setPassword] = useState('')
  const [reason, setReason] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)

  const close = (next: boolean) => {
    if (!next) {
      setPassword('')
      setReason('')
      setFieldError(null)
    }
    onOpenChange(next)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!password) {
      setFieldError('Enter your password.')
      return
    }
    request.mutate(
      { password, reason: reason.trim() || undefined },
      {
        onSuccess: () => {
          toast.success('Your account is scheduled for deletion.')
          close(false)
        },
        onError: (err) => {
          if (isApiError(err) && err.fieldErrors.password) setFieldError(err.fieldErrors.password)
          else toast.error(errorMessage(err))
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Delete your account</DialogTitle>
            <DialogDescription>
              Your account will be deleted in {graceDays} days. You can cancel until then.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-5 space-y-4">
            <div className="space-y-2">
              <Label htmlFor={passwordId}>Password</Label>
              <Input
                id={passwordId}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  setFieldError(null)
                }}
                aria-invalid={!!fieldError}
                aria-describedby={fieldError ? `${passwordId}-error` : undefined}
              />
              {fieldError && (
                <p id={`${passwordId}-error`} className="text-[0.8125rem] text-destructive">
                  {fieldError}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor={reasonId}>
                Why are you leaving? <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Textarea
                id={reasonId}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={() => close(false)}>
              Keep my account
            </Button>
            <Button type="submit" variant="destructive" disabled={request.isPending}>
              {request.isPending && <LoaderCircle className="animate-spin" />}
              Schedule deletion
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeletionBody({ state }: { state: DeletionState }) {
  const cancel = useCancelDeletion()
  const [open, setOpen] = useState(false)
  const scheduled = state.request

  if (scheduled) {
    return (
      <CardContent className="space-y-4 border-t py-5">
        <div className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm">
          <p className="font-medium">
            Your account will be deleted on{' '}
            <time dateTime={scheduled.scheduled_for}>{formatDate(scheduled.scheduled_for)}</time>.
          </p>
          {scheduled.blocked_reason ? (
            <p className="mt-1 text-muted-foreground">
              It can’t be deleted until this is settled: {scheduled.blocked_reason}
            </p>
          ) : (
            <p className="mt-1 text-muted-foreground">Until then you can keep using BountyFlow or cancel.</p>
          )}
        </div>
        <Button
          variant="outline"
          disabled={cancel.isPending}
          onClick={() =>
            cancel.mutate(undefined, {
              onSuccess: () => toast.success('Deletion cancelled. Your account stays.'),
              onError: (e) => toast.error(errorMessage(e)),
            })
          }
        >
          {cancel.isPending && <LoaderCircle className="animate-spin" />}
          Cancel deletion
        </Button>
      </CardContent>
    )
  }

  return (
    <CardContent className="space-y-4 border-t py-5">
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        <li>Erased: your email, name, username, profile, skills, notifications and application texts.</li>
        <li>
          Kept under a pseudonym: payments, escrows, on-chain transactions and approved work, which the law
          requires us to keep. Transactions stay public on the Stellar network.
        </li>
      </ul>
      {state.blockers.length > 0 && (
        <div className="rounded-lg border px-4 py-3 text-sm">
          <p className="flex items-center gap-2 font-medium">
            <ShieldAlert className="size-4 text-warning" aria-hidden />
            Settle these first
          </p>
          <ul className="mt-2 space-y-1.5">
            {state.blockers.map((b) => (
              <li key={b.kind} className="text-muted-foreground">
                {b.message}
                {b.count > 1 && <span className="amount"> ({b.count})</span>}
                {b.links[0] && (
                  <>
                    {' '}
                    <Link to={b.links[0]} className="font-medium text-primary-emphasis hover:underline">
                      Open
                    </Link>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Button variant="destructive" disabled={state.blockers.length > 0} onClick={() => setOpen(true)}>
        <Trash2 />
        Delete account
      </Button>
      <DeleteDialog open={open} onOpenChange={setOpen} graceDays={state.grace_days} />
    </CardContent>
  )
}

function DeletionCard() {
  const query = useDeletionState()
  return (
    <Section
      id="delete"
      title="Delete account"
      description="Deletion happens after a grace period, so you can change your mind."
    >
      <CardQuery query={query} skeleton="app-privacy-deletion" rows={2}>
        {(state) => <DeletionBody state={state} />}
      </CardQuery>
    </Section>
  )
}

export default function PrivacyPage() {
  return (
    <div className="lg:max-w-252">
      <PageHeader title="Privacy and data" />
      <AccountLayout>
        <ExportCard />
        <LegalCard />
        <DeletionCard />
      </AccountLayout>
    </div>
  )
}
