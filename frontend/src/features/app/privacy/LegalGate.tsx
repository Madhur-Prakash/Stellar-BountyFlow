import { ExternalLink, LoaderCircle, LogOut, ScrollText } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Logo } from '@/components/brand/Logo'
import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { errorMessage } from '@/lib/api/client'
import { useAcceptLegal, useLegalStatus, useLogout, useMe } from '@/lib/api/queries'
import type { LegalDocument, LegalVersion } from '@/lib/api/types'
import { formatDate } from '@/lib/format'
import { useAuthUi } from '@/stores/auth-ui'

const DOCUMENTS: Record<LegalDocument, { label: string; path: string; link: string }> = {
  TERMS: { label: 'Terms of service', path: '/terms', link: 'Read the terms' },
  PRIVACY: { label: 'Privacy notice', path: '/privacy', link: 'Read the privacy notice' },
}

/** One changed document: what it is, the version, when it applies, and what changed. */
function VersionItem({ version, upcoming }: { version: LegalVersion; upcoming?: boolean }) {
  const doc = DOCUMENTS[version.document]
  return (
    <li className="rounded-lg border bg-surface/60 px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-sm font-medium">{doc.label}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {version.version}, {upcoming ? 'from' : 'since'} {formatDate(version.effective_at)}
        </span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{version.summary}</p>
      <Link
        to={doc.path}
        target="_blank"
        rel="noopener"
        className="mt-2 inline-flex items-center gap-1 text-[0.8125rem] font-medium text-primary-emphasis hover:underline"
      >
        {doc.link}
        <ExternalLink className="size-3.5" aria-hidden />
        <span className="sr-only">(opens in a new tab)</span>
      </Link>
    </li>
  )
}

function Gate({ versions }: { versions: LegalVersion[] }) {
  const accept = useAcceptLegal()
  const logout = useLogout()
  const navigate = useNavigate()
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <SkipLink />
      <header className="flex h-16 items-center px-4 sm:px-6">
        <Logo />
      </header>
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="flex flex-1 items-start justify-center px-4 pt-6 pb-16 outline-none sm:items-center sm:px-6"
      >
        <section
          aria-labelledby="legal-gate-h"
          className="w-full max-w-xl rounded-xl border bg-card p-6 shadow-soft sm:p-8"
        >
          <span className="flex size-9 items-center justify-center rounded-lg border bg-surface text-muted-foreground">
            <ScrollText className="size-4" aria-hidden />
          </span>
          <h1 id="legal-gate-h" className="mt-5 font-display text-2xl leading-tight tracking-[-0.02em]">
            We’ve updated our terms
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Accept the updated versions to keep using your workspace.
          </p>
          <ul className="mt-5 space-y-3">
            {versions.map((v) => (
              <VersionItem key={v.id} version={v} />
            ))}
          </ul>
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
            <Button
              variant="ghost"
              onClick={() => {
                useAuthUi.getState().setSigningOut(true)
                logout.mutate(undefined, { onSettled: () => void navigate('/', { replace: true }) })
              }}
            >
              <LogOut /> Sign out
            </Button>
            <Button
              onClick={() =>
                accept.mutate(
                  versions.map((v) => v.id),
                  { onError: (e) => toast.error(errorMessage(e)) },
                )
              }
              disabled={accept.isPending}
            >
              {accept.isPending && <LoaderCircle className="animate-spin" />}
              Accept and continue
            </Button>
          </div>
        </section>
      </main>
    </div>
  )
}

/**
 * Holds the workspace back until the user has accepted the terms and privacy notice versions in effect. While
 * the status loads, or if it cannot be loaded, the workspace renders as usual (the API stays the authority).
 */
export function LegalGate({ children }: { children: ReactNode }) {
  const { data: me } = useMe()
  const { data: status } = useLegalStatus(!!me)
  if (status?.needs_acceptance) {
    const pending = status.documents.filter((d) => d.current && !d.accepted_current).map((d) => d.current!)
    return <Gate versions={pending} />
  }
  return <>{children}</>
}

/** Advance notice of a scheduled version, above the workspace content, with an early accept. */
export function LegalNotice() {
  const { data: me } = useMe()
  const { data: status } = useLegalStatus(!!me)
  const accept = useAcceptLegal()
  const [open, setOpen] = useState(false)
  if (!status?.upcoming_pending) return null
  const upcoming = status.documents.filter((d) => d.upcoming && !d.accepted_upcoming).map((d) => d.upcoming!)
  if (upcoming.length === 0) return null
  const first = upcoming.reduce((a, b) => (a.effective_at <= b.effective_at ? a : b))
  const names = upcoming.map((v) => DOCUMENTS[v.document].label.toLowerCase()).join(' and ')
  return (
    <section
      aria-label="Upcoming changes to our terms"
      className="border-b bg-surface/70 px-4 py-2.5 sm:px-6 lg:px-8"
    >
      <div className="mx-auto flex w-full max-w-384 flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-[0.8125rem]">
          Our updated {names} take{upcoming.length === 1 ? 's' : ''} effect on{' '}
          <time dateTime={first.effective_at} className="font-medium">
            {formatDate(first.effective_at)}
          </time>
          .
        </p>
        <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
          Review changes
        </Button>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Upcoming changes</DialogTitle>
            <DialogDescription>
              You can accept now or when they take effect. After that date you’ll be asked before continuing.
            </DialogDescription>
          </DialogHeader>
          <ul className="space-y-3">
            {upcoming.map((v) => (
              <VersionItem key={v.id} version={v} upcoming />
            ))}
          </ul>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Later
            </Button>
            <Button
              disabled={accept.isPending}
              onClick={() =>
                accept.mutate(
                  upcoming.map((v) => v.id),
                  {
                    onSuccess: () => {
                      setOpen(false)
                      toast.success('Thanks. Your acceptance is recorded.')
                    },
                    onError: (e) => toast.error(errorMessage(e)),
                  },
                )
              }
            >
              {accept.isPending && <LoaderCircle className="animate-spin" />}
              Accept
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
