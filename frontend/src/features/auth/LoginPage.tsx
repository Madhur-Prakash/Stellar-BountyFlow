import { zodResolver } from '@hookform/resolvers/zod'
import { Clock3, LoaderCircle, Mail } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { useLogin } from '@/lib/api/queries/auth'
import type { Me } from '@/lib/api/types'
import { postLoginPath, safeNext } from '@/lib/auth-redirect'
import { applyApiErrors } from '@/lib/form-errors'
import { useAuthUi } from '@/stores/auth-ui'

import { AUTH_LINK, AuthCard, FormErrorAlert } from './AuthCard'
import { IconInput, PasswordInput } from './PasswordInput'
import { loginSchema, type LoginValues } from './schemas'

export default function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const login = useLogin()
  const sessionExpired = useAuthUi((s) => s.sessionExpired)
  const clearSessionExpired = useAuthUi((s) => s.clearSessionExpired)
  const lastEmail = useAuthUi((s) => s.lastEmail)
  const [formError, setFormError] = useState<string | null>(null)

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: lastEmail ?? '', password: '' },
  })

  const onLoggedIn = (me: Me) => {
    clearSessionExpired()
    navigate(postLoginPath(me, next), { replace: true })
  }

  const onSubmit = form.handleSubmit((values) => {
    setFormError(null)
    login.mutate(values, {
      onSuccess: onLoggedIn,
      onError: (e) => setFormError(applyApiErrors(e, form.setError, ['email', 'password'])),
    })
  })

  return (
    <AuthCard
      title="Sign in to BountyFlow"
      description={
        next ? 'Sign in to continue where you left off.' : 'Welcome back. Enter your details to continue.'
      }
      footer={
        <>
          New to BountyFlow?{' '}
          <Link to={next ? `/register?next=${encodeURIComponent(next)}` : '/register'} className={AUTH_LINK}>
            Create an account
          </Link>
        </>
      }
    >
      {sessionExpired && (
        <Alert variant="info" className="mb-5">
          <Clock3 />
          <AlertTitle>Your session expired</AlertTitle>
          <AlertDescription>Sign in again to continue.</AlertDescription>
        </Alert>
      )}
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
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between gap-3">
                  <FormLabel className="text-[0.8125rem]">Password</FormLabel>
                  <Link
                    to="/forgot-password"
                    className="text-[0.8125rem] text-muted-foreground transition-colors hover:text-primary-emphasis"
                  >
                    Forgot password?
                  </Link>
                </div>
                <FormControl>
                  <PasswordInput autoComplete="current-password" {...field} />
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
            disabled={login.isPending}
          >
            {login.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Sign in
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
