import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, Mail, MailCheck } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { errorMessage, isApiError } from '@/lib/api/client'
import { useForgotPassword } from '@/lib/api/queries/auth'

import { AUTH_LINK, AuthCard, FormErrorAlert } from './AuthCard'
import { IconInput } from './PasswordInput'
import { forgotPasswordSchema, type ForgotPasswordValues } from './schemas'

// Never reveals whether an account exists for the address.
const GENERIC_MESSAGE = 'If an account exists for that email, we’ve sent it a link to reset your password.'

export default function ForgotPasswordPage() {
  const forgot = useForgotPassword()
  const [sent, setSent] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ForgotPasswordValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: '' },
  })

  const onSubmit = form.handleSubmit(({ email }) => {
    setFormError(null)
    forgot.mutate(email, {
      onSuccess: () => setSent(true),
      onError: (e) => {
        // Only surface transport / rate-limit problems; never reveal whether an account exists.
        if (isApiError(e) && (e.code === 'rate_limited' || e.code === 'network_error' || e.status >= 500)) {
          setFormError(errorMessage(e))
        } else {
          setSent(true)
        }
      },
    })
  })

  if (sent) {
    return (
      <AuthCard icon={MailCheck} title="Check your email" description={GENERIC_MESSAGE}>
        <Button asChild variant="outline" className="w-full">
          <Link to="/login">Back to sign in</Link>
        </Button>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title="Reset your password"
      description="Enter your email and we’ll send you a reset link."
      footer={
        <>
          Remember your password?{' '}
          <Link to="/login" className={AUTH_LINK}>
            Sign in
          </Link>
        </>
      }
    >
      <Form {...form}>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-[0.8125rem]">Email</FormLabel>
                <FormControl>
                  <IconInput
                    icon={Mail}
                    type="email"
                    autoComplete="email"
                    inputMode="email"
                    placeholder="you@example.com"
                    {...field}
                  />
                </FormControl>
                <FormMessage className="text-[0.8125rem]" />
              </FormItem>
            )}
          />
          <FormErrorAlert message={formError} />
          <Button type="submit" size="lg" className="mt-1 w-full" disabled={forgot.isPending}>
            {forgot.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Send reset link
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
