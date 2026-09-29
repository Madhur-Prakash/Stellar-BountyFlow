import { zodResolver } from '@hookform/resolvers/zod'
import { ExternalLink, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import { EmptyState } from '@/components/layout/EmptyState'
import { LoadingState } from '@/components/layout/LoadingState'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import { FormErrorAlert } from '@/features/auth/AuthCard'
import { USERNAME_RE } from '@/features/auth/schemas'
import { useMe } from '@/lib/api/queries/auth'
import { useUpdateMe } from '@/lib/api/queries/users'
import type { Me } from '@/lib/api/types'
import { applyApiErrors } from '@/lib/form-errors'

import { WalletAssetsCard } from './assets/WalletAssetsCard'
import { MyReputationSection } from '@/features/reputation/MyReputationSection'

import { AccountLayout } from './AccountNav'
import { LinkedWalletsCard } from './wallets/LinkedWalletsCard'
import { PasskeyWalletCard } from './wallets/PasskeyWalletCard'

const optionalHttps = z
  .string()
  .trim()
  .refine((v) => v === '' || /^https:\/\/[^\s]+$/i.test(v), 'Use a full https:// URL.')

/** Distinct comma-separated entries; the API accepts at most 15 skills / interests. */
const distinctCount = (v: string) =>
  new Set(
    v
      .split(',')
      .map((x) => x.trim().toLowerCase())
      .filter(Boolean),
  ).size

const schema = z.object({
  display_name: z.string().trim().min(1, 'Required.').max(60, 'Keep it under 60 characters.'),
  username: z.string().trim().regex(USERNAME_RE, '3–30 chars: lowercase letters, numbers, _ or -'),
  bio: z.string().trim().max(1000, 'Keep it under 1,000 characters.'),
  avatar_url: optionalHttps,
  skills: z
    .string()
    .max(600)
    .refine((v) => distinctCount(v) <= 15, 'Add at most 15 skills.'),
  interests: z
    .string()
    .max(600)
    .refine((v) => distinctCount(v) <= 15, 'Add at most 15 interests.'),
  github_url: optionalHttps,
  portfolio_url: optionalHttps,
  wants_to_request: z.boolean(),
  wants_to_contribute: z.boolean(),
})
type Values = z.infer<typeof schema>

const toList = (v: string) =>
  v
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

function ProfileForm({ me }: { me: Me }) {
  const update = useUpdateMe()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      display_name: me.display_name,
      username: me.username,
      bio: me.bio ?? '',
      avatar_url: me.avatar_url ?? '',
      skills: me.skills.join(', '),
      interests: me.interests.join(', '),
      github_url: me.github_url ?? '',
      portfolio_url: me.portfolio_url ?? '',
      wants_to_request: me.wants_to_request,
      wants_to_contribute: me.wants_to_contribute,
    },
  })

  const onSubmit = form.handleSubmit((v) => {
    setFormError(null)
    update.mutate(
      {
        display_name: v.display_name,
        username: v.username,
        bio: v.bio || null,
        avatar_url: v.avatar_url || null,
        skills: toList(v.skills).map((s) => s.toLowerCase()),
        interests: toList(v.interests),
        github_url: v.github_url || null,
        portfolio_url: v.portfolio_url || null,
        wants_to_request: v.wants_to_request,
        wants_to_contribute: v.wants_to_contribute,
      },
      {
        onSuccess: () => toast.success('Profile updated'),
        onError: (e) =>
          setFormError(
            applyApiErrors(e, form.setError, [
              'display_name',
              'username',
              'bio',
              'avatar_url',
              'github_url',
              'portfolio_url',
            ]),
          ),
      },
    )
  })

  const text = (
    name: keyof Values,
    label: string,
    opts: { description?: string; placeholder?: string; area?: boolean } = {},
  ) => (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem className="content-start">
          <FormLabel>{label}</FormLabel>
          <FormControl>
            {opts.area ? (
              <Textarea rows={4} placeholder={opts.placeholder} {...field} value={String(field.value)} />
            ) : (
              <Input placeholder={opts.placeholder} {...field} value={String(field.value)} />
            )}
          </FormControl>
          {opts.description && (
            <FormDescription className="text-[0.8125rem]">{opts.description}</FormDescription>
          )}
          <FormMessage />
        </FormItem>
      )}
    />
  )

  return (
    <Form {...form}>
      <form onSubmit={onSubmit} noValidate>
        <CardContent className="space-y-5 pb-6">
          <div className="grid gap-5 sm:grid-cols-2">
            {text('display_name', 'Display name')}
            {text('username', 'Username', { description: 'Your public profile lives at /u/username.' })}
          </div>
          {text('bio', 'Bio', { area: true })}
          {text('avatar_url', 'Avatar URL', { placeholder: 'https://…' })}
          <Separator />
          <div className="grid gap-5 sm:grid-cols-2">
            {text('skills', 'Skills', { description: 'Comma separated.' })}
            {text('interests', 'Interests', { description: 'Comma separated.' })}
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            {text('github_url', 'GitHub URL', { placeholder: 'https://github.com/you' })}
            {text('portfolio_url', 'Portfolio URL', { placeholder: 'https://…' })}
          </div>
          <Separator />
          <fieldset className="space-y-2.5">
            <legend className="text-sm font-medium">I use BountyFlow to…</legend>
            <div className="flex flex-wrap gap-x-8 gap-y-2.5 pt-2.5">
              {(['wants_to_request', 'wants_to_contribute'] as const).map((name) => (
                <FormField
                  key={name}
                  control={form.control}
                  name={name}
                  render={({ field }) => (
                    <FormItem className="flex items-center gap-3">
                      <FormControl>
                        <Checkbox checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} />
                      </FormControl>
                      <FormLabel className="font-normal">
                        {name === 'wants_to_request' ? 'Post bounties' : 'Find work'}
                      </FormLabel>
                    </FormItem>
                  )}
                />
              ))}
            </div>
          </fieldset>
          <FormErrorAlert message={formError} />
        </CardContent>
        <CardFooter className="justify-end gap-3 px-5 py-3">
          <Button type="submit" disabled={update.isPending || !form.formState.isDirty}>
            {update.isPending && <LoaderCircle className="animate-spin" />} Save changes
          </Button>
        </CardFooter>
      </form>
    </Form>
  )
}

export default function ProfilePage() {
  const { data: me, isPending } = useMe()
  if (isPending) return <LoadingState label="Loading profile" />
  if (!me) return <EmptyState title="Not signed in" />
  return (
    <div className="lg:max-w-252">
      <PageHeader
        breadcrumbs={[{ label: 'Workspace', to: '/app' }, { label: 'Profile' }]}
        title="Profile"
        description="How you appear to requesters and contributors. Everything here except wallets is self-reported."
        actions={
          <Button asChild variant="outline">
            <Link to={`/u/${me.username}`}>
              View public profile <ExternalLink />
            </Link>
          </Button>
        }
      />
      <AccountLayout>
        <section id="details" aria-labelledby="details-h">
          <Card className="gap-0">
            <CardHeader className="pb-5">
              <CardTitle>
                <h2 id="details-h">Public details</h2>
              </CardTitle>
              <CardDescription>Shown on your public profile.</CardDescription>
            </CardHeader>
            <ProfileForm me={me} />
          </Card>
        </section>
        <LinkedWalletsCard />
        <PasskeyWalletCard />
        <WalletAssetsCard />
        <MyReputationSection username={me.username} />
      </AccountLayout>
    </div>
  )
}
