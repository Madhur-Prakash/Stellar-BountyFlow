import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { useRegister } from '@/lib/api/queries/auth'
import { postLoginPath, safeNext } from '@/lib/auth-redirect'
import { applyApiErrors } from '@/lib/form-errors'

import { AuthCard, FormErrorAlert } from './AuthCard'
import { PasswordInput, PasswordStrengthMeter } from './PasswordInput'
import { registerSchema, type RegisterValues } from './schemas'

const FIELDS = ['email', 'username', 'display_name', 'password'] as const

export default function RegisterPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const register = useRegister()
  const [formError, setFormError] = useState<string | null>(null)

  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      email: '',
      username: '',
      display_name: '',
      password: '',
      confirm_password: '',
      accept_terms: false,
    },
    mode: 'onTouched',
  })
  const password = useWatch({ control: form.control, name: 'password' })

  const onSubmit = form.handleSubmit(({ email, username, display_name, password: pw }) => {
    setFormError(null)
    register.mutate(
      { email, username, display_name, password: pw },
      {
        onSuccess: (me) => {
          toast.success('Account created. Check your inbox to verify your email.')
          navigate(postLoginPath(me, next), { replace: true })
        },
        onError: (e) => setFormError(applyApiErrors(e, form.setError, FIELDS)),
      },
    )
  })

  return (
    <AuthCard
      title="Create your account"
      description="Post bounties, apply for work, and get paid from escrow on Stellar."
      footer={
        <>
          Already have an account?{' '}
          <Link
            to={next ? `/login?next=${encodeURIComponent(next)}` : '/login'}
            className="font-medium text-foreground underline underline-offset-4"
          >
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
          <div className="grid gap-5 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Username</FormLabel>
                  <FormControl>
                    <Input
                      autoComplete="username"
                      autoCapitalize="none"
                      spellCheck={false}
                      {...field}
                      onChange={(e) => field.onChange(e.target.value.toLowerCase())}
                    />
                  </FormControl>
                  <FormDescription>3–30 chars: a–z, 0–9, _ or -</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="display_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Display name</FormLabel>
                  <FormControl>
                    <Input autoComplete="name" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Password</FormLabel>
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
                <FormLabel>Confirm password</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="accept_terms"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-start gap-3">
                  <FormControl>
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={(v) => field.onChange(v === true)}
                      className="mt-0.5"
                    />
                  </FormControl>
                  <FormLabel className="leading-snug font-normal">
                    <span>
                      I agree to the{' '}
                      <Link to="/terms" target="_blank" className="underline underline-offset-4">
                        terms
                      </Link>{' '}
                      and{' '}
                      <Link to="/privacy" target="_blank" className="underline underline-offset-4">
                        privacy notice
                      </Link>
                      .
                    </span>
                  </FormLabel>
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormErrorAlert message={formError} />
          <Button type="submit" size="lg" className="w-full" disabled={register.isPending}>
            {register.isPending ? <LoaderCircle className="animate-spin" /> : <UserPlus />}
            Create account
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
