import {
  CircleAlert,
  ExternalLink,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
  LoaderCircle,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { MetaList } from '@/components/bounty/MetaList'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { errorMessage } from '@/lib/api/client'
import { useAddPullRequest, useRecheckPullRequests, useRemovePullRequest } from '@/lib/api/queries/github'
import { MAX_PULL_REQUESTS, type OnchainReview, type PullRequest } from '@/lib/api/types'
import { formatDateTime, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

import {
  checksLabel,
  isPullRequestUrl,
  prLabel,
  qualifiesForMergeRequirement,
  STATE_LABELS,
  STATE_VARIANTS,
  VERIFICATION_LABELS,
  VERIFICATION_VARIANTS,
  verificationDetail,
} from './pr-display'

function StateIcon({ pr }: { pr: PullRequest }) {
  const Icon = pr.state === 'MERGED' ? GitMerge : pr.state === 'CLOSED' ? GitPullRequestClosed : GitPullRequest
  return (
    <span
      className={cn(
        'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border bg-surface',
        pr.state === 'MERGED' ? 'text-cyan' : 'text-muted-foreground',
      )}
      aria-hidden
    >
      <Icon className="size-3.5" />
    </span>
  )
}

/** One linked pull request: repository and number, title, author, state, checks, and the verdict. */
export function PullRequestCard({
  pr,
  onRemove,
  removing,
}: {
  pr: PullRequest
  onRemove?: () => void
  removing?: boolean
}) {
  const checks = checksLabel(pr)
  const detail = pr.verification === 'VERIFIED' ? null : verificationDetail(pr)
  const failing = pr.check_runs.filter((c) => c.conclusion && !['success', 'neutral', 'skipped'].includes(c.conclusion))
  return (
    <li className="flex items-start gap-3 py-3 first:pt-0 last:pb-0" data-testid="pull-request">
      <StateIcon pr={pr} />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <a
            href={pr.url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="inline-flex min-h-7 items-center gap-1 font-mono text-[0.8125rem] font-medium break-all hover:underline"
          >
            {prLabel(pr)}
            <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
          {pr.state && <Badge variant={STATE_VARIANTS[pr.state]}>{pr.draft && pr.state === 'OPEN' ? 'Draft' : STATE_LABELS[pr.state]}</Badge>}
          <Badge variant={VERIFICATION_VARIANTS[pr.verification]}>{VERIFICATION_LABELS[pr.verification]}</Badge>
        </div>
        {pr.title && <p className="text-sm leading-snug">{pr.title}</p>}
        <MetaList>
          {pr.author_login && <span>@{pr.author_login}</span>}
          {checks && (
            <span className={cn(pr.checks === 'FAILURE' && 'text-destructive')}>
              {checks}
              {failing.length > 0 && `: ${failing.slice(0, 3).map((c) => c.name).join(', ')}`}
            </span>
          )}
          {pr.merged_at && <span>Merged {formatRelative(pr.merged_at)}</span>}
          {pr.last_checked_at && (
            <time dateTime={pr.last_checked_at} title={formatDateTime(pr.last_checked_at)}>
              Checked {formatRelative(pr.last_checked_at)}
            </time>
          )}
        </MetaList>
        {detail && (
          <p className="flex items-start gap-1.5 text-[0.8125rem] text-muted-foreground">
            <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {detail}
          </p>
        )}
      </div>
      {onRemove && (
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          aria-label={`Unlink ${prLabel(pr)}`}
          disabled={removing}
          onClick={onRemove}
        >
          {removing ? <LoaderCircle className="animate-spin" /> : <Trash2 />}
        </Button>
      )}
    </li>
  )
}

function AddPullRequest({ submissionId, disabled }: { submissionId: string; disabled: boolean }) {
  const id = useId()
  const add = useAddPullRequest(submissionId)
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  return (
    <form
      className="space-y-1.5"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        if (!isPullRequestUrl(url)) {
          setError('Use a GitHub pull request URL, like https://github.com/owner/repo/pull/123.')
          return
        }
        setError(null)
        add.mutate(url.trim(), {
          onSuccess: () => {
            setUrl('')
            toast.success('Pull request linked')
          },
          onError: (err) => setError(errorMessage(err)),
        })
      }}
    >
      <Label htmlFor={id} className="text-[0.8125rem]">
        Link a pull request
      </Label>
      <div className="flex flex-wrap gap-2">
        <Input
          id={id}
          type="url"
          inputMode="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo/pull/123"
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-err` : undefined}
          disabled={disabled}
          className="min-w-0 flex-1 font-mono text-sm"
        />
        <Button type="submit" variant="outline" className="shrink-0" disabled={disabled || add.isPending}>
          {add.isPending ? <LoaderCircle className="animate-spin" /> : <Plus />} Link
        </Button>
      </div>
      {error && (
        <p id={`${id}-err`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  )
}

/**
 * The pull requests linked to a submission, for both sides. The contributor can link and unlink them while the
 * submission is open; either side can ask for a fresh check.
 */
export function PullRequestList({
  submissionId,
  pullRequests,
  requireMerged = false,
  editable = false,
  showGitHubHint = false,
  review = null,
  perspective = 'requester',
  className,
}: {
  submissionId: string
  pullRequests: PullRequest[]
  requireMerged?: boolean
  editable?: boolean
  /** The viewer is the contributor and has not linked a GitHub account. */
  showGitHubHint?: boolean
  /** The escrow's on-chain review clock for this submission, when there is one. */
  review?: OnchainReview | null
  perspective?: 'requester' | 'contributor'
  className?: string
}) {
  const recheck = useRecheckPullRequests(submissionId)
  const remove = useRemovePullRequest(submissionId)
  const satisfied = pullRequests.some(qualifiesForMergeRequirement)
  const clockRunning = review?.state === 'PENDING'
  if (pullRequests.length === 0 && !editable && !requireMerged) return null

  return (
    <section aria-label="Pull requests" className={cn('rounded-lg border bg-surface/40 p-3 sm:p-4', className)}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <GitPullRequest className="size-4 text-muted-foreground" aria-hidden /> Pull requests
          {requireMerged && (
            <Badge variant={satisfied ? 'info' : 'warning'}>
              {satisfied ? 'Merged PR verified' : 'Merged PR required'}
            </Badge>
          )}
        </h3>
        {pullRequests.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            disabled={recheck.isPending}
            onClick={() =>
              recheck.mutate(undefined, {
                onSuccess: () => toast.success('Checked with GitHub'),
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            {recheck.isPending ? <LoaderCircle className="animate-spin" /> : <RefreshCw />} Check again
          </Button>
        )}
      </div>
      {pullRequests.length > 0 ? (
        <ul className="divide-y">
          {pullRequests.map((pr) => (
            <PullRequestCard
              key={pr.id}
              pr={pr}
              removing={remove.isPending && remove.variables === pr.id}
              onRemove={
                editable
                  ? () =>
                      remove.mutate(pr.id, {
                        onSuccess: () => toast.success('Pull request unlinked'),
                        onError: (e) => toast.error(errorMessage(e)),
                      })
                  : undefined
              }
            />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No pull requests linked.</p>
      )}
      {requireMerged && !satisfied && clockRunning && (
        <Alert variant="warning" className="mt-3">
          <CircleAlert />
          <AlertTitle>
            {perspective === 'requester'
              ? 'Approval is blocked, but the review clock is not'
              : 'The requester cannot approve yet'}
          </AlertTitle>
          <AlertDescription>
            {perspective === 'requester' ? (
              <>
                This bounty needs a merged pull request before you can approve. The escrow&rsquo;s review clock
                keeps running{' '}
                {review?.claimable_at && <>until {formatDateTime(review.claimable_at)}, </>}and silence pays the
                contributor: answer on-chain with &ldquo;Request revision&rdquo; or &ldquo;Reject&rdquo; to stop
                it.
              </>
            ) : (
              <>
                Approval needs a merged pull request from your verified GitHub account. Merge it, or expect the
                requester to answer on-chain before the review window closes.
              </>
            )}
          </AlertDescription>
        </Alert>
      )}
      {showGitHubHint && (
        <p className="mt-3 flex items-start gap-1.5 text-[0.8125rem] text-muted-foreground">
          <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            Authorship is verified against your GitHub account.{' '}
            <Link to="/app/settings#github" className="font-medium text-primary-emphasis hover:underline">
              Link GitHub in settings
            </Link>
          </span>
        </p>
      )}
      {editable && (
        <div className="mt-3 border-t pt-3">
          <AddPullRequest submissionId={submissionId} disabled={pullRequests.length >= MAX_PULL_REQUESTS} />
        </div>
      )}
    </section>
  )
}
