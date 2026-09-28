import { CheckCircle2, CircleAlert, LoaderCircle, MailCheck } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api/client'
import { useMe, useResendVerification, useVerifyEmail } from '@/lib/api/queries/auth'

import { AuthCard } from './AuthCard'

function ResendButton() {
  const { data: me } = useMe()
  const resend = useResendVerification()
  if (!me) {
    return (
      <Button asChild variant="outline" className="w-full">
        <Link to="/login?next=%2Fverify-email">Sign in to resend the email</Link>
      </Button>
    )
  }
  if (me.email_verified) return null
  return (
    <Button
      variant="outline"
      className="w-full"
      disabled={resend.isPending || resend.isSuccess}
      onClick={() =>
        resend.mutate(undefined, {
          onSuccess: () => toast.success(`Verification email sent to ${me.email}`),
          onError: (e) => toast.error(errorMessage(e)),
        })
      }
    >
      {resend.isPending && <LoaderCircle className="animate-spin" />}
      {resend.isSuccess ? 'Email sent. Check your inbox.' : 'Resend verification email'}
    </Button>
  )
}

export default function VerifyEmailPage() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const verify = useVerifyEmail()
  const { mutate: runVerify } = verify
  const { data: me } = useMe()
  const started = useRef<string | null>(null)

  useEffect(() => {
    if (!token || started.current === token) return
    started.current = token
    runVerify(token)
  }, [token, runVerify])

  if (!token) {
    return (
      <AuthCard
        title={me?.email_verified ? 'Email verified' : 'Check your inbox'}
        description={
          me?.email_verified
            ? 'Your email address is already confirmed.'
            : 'We sent a verification link to your email address. Open it on this device to confirm your account.'
        }
      >
        <div className="space-y-3">
          <MailCheck className="size-8 text-primary-emphasis" aria-hidden />
          {me?.email_verified ? (
            <Button asChild className="w-full">
              <Link to="/app">Go to dashboard</Link>
            </Button>
          ) : (
            <ResendButton />
          )}
        </div>
      </AuthCard>
    )
  }

  if (verify.isError) {
    return (
      <AuthCard title="Verification failed" description={errorMessage(verify.error)}>
        <div className="space-y-3" role="alert">
          <CircleAlert className="size-8 text-destructive" aria-hidden />
          <p className="text-sm text-muted-foreground">
            The link may have expired or already been used. Request a new one below.
          </p>
          <ResendButton />
        </div>
      </AuthCard>
    )
  }

  if (verify.isSuccess) {
    return (
      <AuthCard
        title="Email verified"
        description="Your email address is confirmed. You can now publish bounties."
      >
        <div className="space-y-3" aria-live="polite">
          <CheckCircle2 className="size-8 text-success" aria-hidden />
          <Button asChild className="w-full">
            <Link to={me ? '/app' : '/login'}>{me ? 'Continue to dashboard' : 'Sign in'}</Link>
          </Button>
        </div>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Verifying your email" description="One moment…">
      <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" aria-hidden /> Confirming your verification link
      </div>
    </AuthCard>
  )
}
