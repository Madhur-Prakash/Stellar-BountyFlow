import { CircleAlert, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api/client'
import { useGitHubOAuthCallback } from '@/lib/api/queries/github'

/**
 * Where GitHub sends the browser back after "Connect with GitHub". The code and state are handed to the API,
 * which exchanges them server-side; this page never sees a token. Only reachable when the server has an OAuth
 * app configured — gist verification is the route that always works.
 */
export default function GitHubCallbackPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const callback = useGitHubOAuthCallback()
  const [failure, setFailure] = useState<string | null>(null)
  const started = useRef(false)

  const code = params.get('code')
  const state = params.get('state')
  const linkProblem = params.get('error')
    ? 'GitHub did not complete the sign-in.'
    : !code || !state
      ? 'This link is missing its sign-in details. Start again from Settings.'
      : null

  useEffect(() => {
    if (started.current || linkProblem || !code || !state) return
    started.current = true
    callback.mutate(
      { code, state },
      {
        onSuccess: (account) => {
          toast.success(`Linked @${account.login}`)
          void navigate('/app/settings#github', { replace: true })
        },
        onError: (e) => setFailure(errorMessage(e)),
      },
    )
  }, [callback, code, linkProblem, navigate, state])

  const error = linkProblem ?? failure

  return (
    <div className="lg:max-w-2xl">
      <PageHeader title="Connecting GitHub" />
      {error ? (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertTitle>GitHub was not linked</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>{error}</p>
            <Button variant="outline" size="sm" onClick={() => void navigate('/app/settings#github')}>
              Back to settings
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" aria-hidden /> Finishing the GitHub sign-in…
        </p>
      )}
    </div>
  )
}
