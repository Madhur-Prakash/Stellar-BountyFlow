import { zodResolver } from '@hookform/resolvers/zod'
import { AtSign, LoaderCircle, Mail, UserRound } from 'lucide-react'
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
import { useRegister } from '@/lib/api/queries/auth'
import { postLoginPath, safeNext } from '@/lib/auth-redirect'
import { applyApiErrors } from '@/lib/form-errors'

import { AUTH_LINK, AuthCard, FormErrorAlert } from './AuthCard'
import { IconInput, NEW_PASSWORD_HINT, PasswordInput, PasswordStrengthMeter } from './PasswordInput'
import { registerSchema, type RegisterValues } from './schemas'

const FIELDS = ['email', 'username', 'display_name', 'password'] as const
const LABEL = 'text-[0.8125rem]'

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
      description="Post bounties and get paid from escrow on Stellar."
      footer={
        <>
          Already have an account?{' '}
          <Link to={next ? `/login?next=${encodeURIComponent(next)}` : '/login'} className={AUTH_LINK}>
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
                <FormLabel className={LABEL}>Email</FormLabel>
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
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel className={LABEL}>Username</FormLabel>
                <FormControl>
                  <IconInput
                    icon={AtSign}
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    {...field}
                    onChange={(e) => field.onChange(e.target.value.toLowerCase())}
                  />
                </FormControl>
                <FormDescription className="text-xs">
                  3 to 30 lowercase letters, numbers, _ or -.
                </FormDescription>
                <FormMessage className="text-[0.8125rem]" />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="display_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel className={LABEL}>Display name</FormLabel>
                <FormControl>
                  <IconInput icon={UserRound} autoComplete="name" {...field} />
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
                <FormLabel className={LABEL}>Password</FormLabel>
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
                <FormLabel className={LABEL}>Confirm password</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" {...field} />
                </FormControl>
                <FormMessage className="text-[0.8125rem]" />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="accept_terms"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-start gap-2.5">
                  <FormControl>
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={(v) => field.onChange(v === true)}
                      className="mt-px"
                    />
                  </FormControl>
                  <FormLabel className="text-[0.8125rem] leading-snug font-normal text-muted-foreground">
                    <span>
                      I agree to the{' '}
                      <Link
                        to="/terms"
                        target="_blank"
                        className="text-foreground underline underline-offset-4"
                      >
                        terms
                      </Link>{' '}
                      and{' '}
                      <Link
                        to="/privacy"
                        target="_blank"
                        className="text-foreground underline underline-offset-4"
                      >
                        privacy notice
                      </Link>
                      .
                    </span>
                  </FormLabel>
                </div>
                <FormMessage className="text-[0.8125rem]" />
              </FormItem>
            )}
          />
          <FormErrorAlert message={formError} />
          <Button type="submit" size="lg" className="mt-1 w-full" disabled={register.isPending}>
            {register.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Create account
          </Button>
        </form>
      </Form>
    </AuthCard>
  )
}
