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
      <Button asChild variant="outline" size="pill" className="w-full">
        <Link to="/login?next=%2Fverify-email">Sign in to resend the email</Link>
      </Button>
    )
  }
  if (me.email_verified) return null
  return (
    <Button
      variant="outline"
      size="pill"
      className="w-full"
      disabled={resend.isPending || resend.isSuccess}
      onClick={() =>
        resend.mutate(undefined, {
          onSuccess: () => toast.success(`Verification email sent to ${me.email}`),
          onError: (e) => toast.error(errorMessage(e)),
        })
      }
    >
      {resend.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
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
    if (me?.email_verified) {
      return (
        <AuthCard
          icon={CheckCircle2}
          tone="success"
          title="Email verified"
          description="Your email is already confirmed."
        >
          <Button asChild variant="inverse" size="pill" className="w-full">
            <Link to="/app">Go to dashboard</Link>
          </Button>
        </AuthCard>
      )
    }
    return (
      <AuthCard
        icon={MailCheck}
        title="Check your inbox"
        description="We sent you a verification link. Open it to confirm your email."
      >
        <ResendButton />
      </AuthCard>
    )
  }

  if (verify.isError) {
    return (
      <AuthCard
        icon={CircleAlert}
        tone="destructive"
        live="alert"
        title="Verification failed"
        description={errorMessage(verify.error)}
      >
        {!me?.email_verified && <ResendButton />}
      </AuthCard>
    )
  }

  if (verify.isSuccess) {
    return (
      <AuthCard
        icon={CheckCircle2}
        tone="success"
        live="status"
        title="Email verified"
        description="You can now publish bounties."
      >
        <Button asChild variant="inverse" size="pill" className="w-full">
          <Link to={me ? '/app' : '/login'}>{me ? 'Continue to dashboard' : 'Sign in'}</Link>
        </Button>
      </AuthCard>
    )
  }

  return (
    <AuthCard icon={LoaderCircle} iconClassName="animate-spin" live="status" title="Verifying your email" />
  )
}
