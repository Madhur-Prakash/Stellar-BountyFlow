import { Check, ExternalLink, LoaderCircle, Unlink } from 'lucide-react'
import { useId, useState } from 'react'
import { toast } from 'sonner'

import { GithubMark } from '@/components/brand/GithubMark'
import { CopyButton } from '@/components/common/CopyButton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { errorMessage } from '@/lib/api/client'
import {
  useGitHubAccount,
  useGitHubChallenge,
  useGitHubConfig,
  useGitHubOAuthStart,
  useUnlinkGitHub,
  useVerifyGist,
} from '@/lib/api/queries/github'
import type { GitHubChallenge } from '@/lib/api/types'
import { formatDate } from '@/lib/format'

/** Step 1 of the gist proof: ask for the username and get the one-time text to publish. */
function StartLinking({ onIssued }: { onIssued: (challenge: GitHubChallenge) => void }) {
  const id = useId()
  const config = useGitHubConfig()
  const challenge = useGitHubChallenge()
  const oauth = useGitHubOAuthStart()
  const [login, setLogin] = useState('')

  return (
    <div className="space-y-4">
      <form
        className="space-y-2"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          challenge.mutate(login.trim(), {
            onSuccess: onIssued,
            onError: (err) => toast.error(errorMessage(err)),
          })
        }}
      >
        <Label htmlFor={id}>GitHub username</Label>
        <div className="flex flex-wrap gap-2">
          <Input
            id={id}
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            placeholder="octocat"
            autoComplete="off"
            spellCheck={false}
            maxLength={40}
            className="min-w-0 flex-1 font-mono text-sm sm:max-w-64"
          />
          <Button type="submit" className="shrink-0" disabled={!login.trim() || challenge.isPending}>
            {challenge.isPending ? <LoaderCircle className="animate-spin" /> : <GithubMark />}
            Continue
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          You prove the account by publishing a one-time text in a public gist. BountyFlow reads it through the
          GitHub API and stores only your username and numeric id.
        </p>
      </form>
      {config.data?.oauth_enabled && (
        <div className="border-t pt-4">
          <Button
            variant="outline"
            disabled={oauth.isPending}
            onClick={() =>
              oauth.mutate(undefined, {
                onSuccess: ({ authorize_url }) => {
                  window.location.href = authorize_url
                },
                onError: (err) => toast.error(errorMessage(err)),
              })
            }
          >
            {oauth.isPending ? <LoaderCircle className="animate-spin" /> : <GithubMark />} Connect with GitHub
          </Button>
        </div>
      )}
    </div>
  )
}

/** Step 2: the challenge is issued; publish it in a gist and paste the gist URL back. */
function FinishLinking({ challenge, onCancel }: { challenge: GitHubChallenge; onCancel: () => void }) {
  const id = useId()
  const verify = useVerifyGist()
  const [url, setUrl] = useState('')

  return (
    <div className="space-y-4">
      <ol className="space-y-3 text-sm">
        <li className="flex gap-3">
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border bg-surface text-xs tabular-nums">
            1
          </span>
          <div className="min-w-0 flex-1 space-y-2">
            <p>
              Create a <span className="font-medium">public</span> gist as{' '}
              <span className="font-mono">@{challenge.login}</span> with a file named{' '}
              <span className="font-mono">{challenge.filename}</span> holding this text.
            </p>
            <div className="flex items-start gap-2 rounded-lg border bg-surface px-3 py-2">
              <code className="min-w-0 flex-1 font-mono text-xs break-all">{challenge.challenge}</code>
              <CopyButton value={challenge.challenge} label="verification text" />
            </div>
            <Button asChild variant="outline" size="sm">
              <a href="https://gist.github.com/" target="_blank" rel="noopener noreferrer">
                <ExternalLink /> New gist
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            </Button>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border bg-surface text-xs tabular-nums">
            2
          </span>
          <form
            className="min-w-0 flex-1 space-y-2"
            noValidate
            onSubmit={(e) => {
              e.preventDefault()
              verify.mutate(url.trim(), {
                onSuccess: (account) => toast.success(`Linked @${account.login}`),
                onError: (err) => toast.error(errorMessage(err)),
              })
            }}
          >
            <Label htmlFor={id}>Paste the gist URL</Label>
            <div className="flex flex-wrap gap-2">
              <Input
                id={id}
                type="url"
                inputMode="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://gist.github.com/…"
                className="min-w-0 flex-1 font-mono text-sm"
              />
              <Button type="submit" className="shrink-0" disabled={!url.trim() || verify.isPending}>
                {verify.isPending ? <LoaderCircle className="animate-spin" /> : <Check />} Verify
              </Button>
            </div>
          </form>
        </li>
      </ol>
      <p className="text-xs text-muted-foreground">
        The text expires {formatDate(challenge.expires_at)}. You can delete the gist once the account is linked.
      </p>
      <Button variant="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  )
}

/** The linked account, with the proof it was verified from. */
function LinkedAccount() {
  const { data: account } = useGitHubAccount()
  const unlink = useUnlinkGitHub()
  if (!account) return null
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-surface">
            <GithubMark className="size-4.5" />
          </span>
          <div className="min-w-0">
            <a
              href={account.profile_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-sm font-medium hover:underline"
            >
              @{account.login}
            </a>
            <p className="text-xs text-muted-foreground">
              Verified {formatDate(account.verified_at)} by{' '}
              {account.method === 'GIST' ? 'a public gist' : 'GitHub sign-in'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="info">
            <Check aria-hidden /> Verified
          </Badge>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            disabled={unlink.isPending}
            onClick={() =>
              unlink.mutate(undefined, {
                onSuccess: () => toast.success('GitHub account unlinked'),
                onError: (err) => toast.error(errorMessage(err)),
              })
            }
          >
            {unlink.isPending ? <LoaderCircle className="animate-spin" /> : <Unlink />} Unlink
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        Pull requests you link to a submission are verified against this account.
      </p>
    </div>
  )
}

/** The GitHub card's body: link an account, or manage the one that is linked. */
export function GitHubSectionBody() {
  const account = useGitHubAccount()
  const config = useGitHubConfig()
  const [challenge, setChallenge] = useState<GitHubChallenge | null>(null)

  return (
    <CardContent className="border-t py-5">
      {account.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : account.data ? (
        <LinkedAccount />
      ) : challenge ? (
        <FinishLinking challenge={challenge} onCancel={() => setChallenge(null)} />
      ) : (
        <StartLinking onIssued={setChallenge} />
      )}
      {config.data && !config.data.authenticated_api && !account.data && (
        <Alert variant="info" className="mt-4">
          <AlertDescription>
            This server reads GitHub without a token, so checks are rate limited and can take a few minutes to
            refresh.
          </AlertDescription>
        </Alert>
      )}
    </CardContent>
  )
}
