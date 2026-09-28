import { MailWarning } from 'lucide-react'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api/client'
import { useResendVerification } from '@/lib/api/queries/auth'

/** Clear "verify your email" prompt with a resend button. */
export function EmailNotVerifiedNotice({
  action = 'publish bounties',
  className,
}: {
  action?: string
  className?: string
}) {
  const resend = useResendVerification()
  return (
    <Alert variant="warning" className={className}>
      <MailWarning />
      <AlertTitle>Verify your email to {action}</AlertTitle>
      <AlertDescription>
        <p>
          We sent a verification link when you registered. Open it to confirm your address, then try again.
        </p>
        <Button
          size="sm"
          variant="outline"
          className="mt-2"
          disabled={resend.isPending || resend.isSuccess}
          onClick={() =>
            resend.mutate(undefined, {
              onSuccess: () => toast.success('Verification email sent'),
              onError: (e) => toast.error(errorMessage(e)),
            })
          }
        >
          {resend.isSuccess ? 'Email sent' : resend.isPending ? 'Sending…' : 'Resend verification email'}
        </Button>
      </AlertDescription>
    </Alert>
  )
}
