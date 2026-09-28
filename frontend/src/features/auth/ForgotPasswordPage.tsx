import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, MailCheck, Send } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { errorMessage, isApiError } from '@/lib/api/client'
import { useForgotPassword } from '@/lib/api/queries/auth'

import { AuthCard, FormErrorAlert } from './AuthCard'
import { forgotPasswordSchema, type ForgotPasswordValues } from './schemas'

const GENERIC_MESSAGE =
  'If an account exists for that address, we’ve sent a link to reset your password. It may take a few minutes to arrive.'

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
      <AuthCard
        title="Check your email"
        description={GENERIC_MESSAGE}
        footer={
          <Link to="/login" className="underline underline-offset-4">
            Back to sign in
          </Link>
        }
      >
        <MailCheck className="size-8 text-primary-emphasis" aria-hidden />
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title="Reset your password"
      description="Enter the email you signed up with and we’ll send you a reset link."
      footer={
        <>
          Remembered it?{' '}
          <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </>
      }
    >
      <Form {...form}>
        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input type="email" autoComplete="email" inputMode="email" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormErrorAlert message={formError} />
          <Button type="submit" size="lg" className="w-full" disabled={forgot.isPending}>
            {forgot.isPending ? <LoaderCircle className="animate-spin" /> : <Send />}
            Send reset link
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
