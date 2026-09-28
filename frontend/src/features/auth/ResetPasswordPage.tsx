import { zodResolver } from '@hookform/resolvers/zod'
import { CircleAlert, KeyRound, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { useResetPassword } from '@/lib/api/queries/auth'
import { applyApiErrors } from '@/lib/form-errors'

import { AuthCard, FormErrorAlert } from './AuthCard'
import { PasswordInput, PasswordStrengthMeter } from './PasswordInput'
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
        title="Reset link missing"
        description="This page needs the link from your password reset email."
        footer={
          <Link to="/forgot-password" className="underline underline-offset-4">
            Request a new link
          </Link>
        }
      >
        <CircleAlert className="size-8 text-warning" aria-hidden />
      </AuthCard>
    )
  }

  const onSubmit = form.handleSubmit(({ password: pw }) => {
    setFormError(null)
    reset.mutate(
      { token, password: pw },
      {
        onSuccess: () => {
          toast.success('Password updated. You were signed out everywhere, so sign in with the new password.')
          navigate('/login', { replace: true })
        },
        onError: (e) => setFormError(applyApiErrors(e, form.setError, ['password'])),
      },
    )
  })

  return (
    <AuthCard
      title="Choose a new password"
      description="Signing in with the new password will sign you out everywhere else."
    >
      <Form {...form}>
        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>New password</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" {...field} />
                </FormControl>
                <PasswordStrengthMeter password={password} />
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Confirm new password</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormErrorAlert message={formError} />
          <Button type="submit" size="lg" className="w-full" disabled={reset.isPending}>
            {reset.isPending ? <LoaderCircle className="animate-spin" /> : <KeyRound />}
            Update password
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
