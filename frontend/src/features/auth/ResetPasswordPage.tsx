import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { useResetPassword } from '@/lib/api/queries/auth'
import { applyApiErrors } from '@/lib/form-errors'

import { AUTH_LINK, AuthCard, FormErrorAlert } from './AuthCard'
import { NEW_PASSWORD_HINT, PasswordInput, PasswordStrengthMeter } from './PasswordInput'
import { resetPasswordSchema, type ResetPasswordValues } from './schemas'

export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const navigate = useNavigate()
  const reset = useResetPassword()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { password: '', confirm_password: '' },
  })
  const password = useWatch({ control: form.control, name: 'password' })

  if (!token) {
    return (
      <AuthCard
        icon={TriangleAlert}
        tone="warning"
        title="Reset link missing"
        description="Open the link from your password reset email, or request a new one."
      >
        <Button asChild variant="inverse" size="pill" className="w-full">
          <Link to="/forgot-password">Request a new link</Link>
        </Button>
      </AuthCard>
    )
  }

  const onSubmit = form.handleSubmit(({ password: pw }) => {
    setFormError(null)
    reset.mutate(
      { token, password: pw },
      {
        onSuccess: () => {
          toast.success('Password updated. Sign in with your new password.')
          navigate('/login', { replace: true })
        },
        onError: (e) => setFormError(applyApiErrors(e, form.setError, ['password'])),
      },
    )
  })

  return (
    <AuthCard
      title="Choose a new password"
      description="Changing your password signs you out on every device."
      footer={
        <Link to="/login" className={AUTH_LINK}>
          Back to sign in
        </Link>
      }
    >
      <Form {...form}>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-[0.8125rem]">New password</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" placeholder={NEW_PASSWORD_HINT} {...field} />
                </FormControl>
                <PasswordStrengthMeter password={password} />
                <FormMessage className="text-[0.8125rem]" />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-[0.8125rem]">Confirm new password</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" {...field} />
                </FormControl>
                <FormMessage className="text-[0.8125rem]" />
              </FormItem>
            )}
          />
          <FormErrorAlert message={formError} />
          <Button
            type="submit"
            variant="inverse"
            size="pill"
            className="mt-2 w-full"
            disabled={reset.isPending}
          >
            {reset.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Update password
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
