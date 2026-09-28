import { zodResolver } from '@hookform/resolvers/zod'
import { Clock3, LoaderCircle, LogIn } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { useLogin } from '@/lib/api/queries/auth'
import type { Me } from '@/lib/api/types'
import { postLoginPath, safeNext } from '@/lib/auth-redirect'
import { applyApiErrors } from '@/lib/form-errors'
import { useAuthUi } from '@/stores/auth-ui'

import { AuthCard, FormErrorAlert } from './AuthCard'
import { PasswordInput } from './PasswordInput'
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
      description={next ? 'Sign in to continue where you left off.' : 'Welcome back.'}
      footer={
        <>
          New to BountyFlow?{' '}
          <Link
            to={next ? `/register?next=${encodeURIComponent(next)}` : '/register'}
            className="font-medium text-foreground underline underline-offset-4"
          >
            Create an account
          </Link>
        </>
      }
    >
      {sessionExpired && (
        <Alert variant="info" className="mb-6">
          <Clock3 />
          <AlertTitle>Your session expired</AlertTitle>
          <AlertDescription>Please sign in again to continue.</AlertDescription>
        </Alert>
      )}
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
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel>Password</FormLabel>
                  <Link
                    to="/forgot-password"
                    className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                  >
                    Forgot password?
                  </Link>
                </div>
                <FormControl>
                  <PasswordInput autoComplete="current-password" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormErrorAlert message={formError} />
          <Button type="submit" size="lg" className="w-full" disabled={login.isPending}>
            {login.isPending ? <LoaderCircle className="animate-spin" /> : <LogIn />}
            Sign in
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
