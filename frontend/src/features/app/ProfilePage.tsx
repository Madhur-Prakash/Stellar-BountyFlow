import { zodResolver } from '@hookform/resolvers/zod'
import { ExternalLink, LoaderCircle, ShieldCheck, Trash2, Wallet } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import { WalletButton } from '@/components/chain/WalletButton'
import { MonoValue } from '@/components/common/MonoValue'
import { EmptyState } from '@/components/layout/EmptyState'
import { LoadingState } from '@/components/layout/LoadingState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import { FormErrorAlert } from '@/features/auth/AuthCard'
import { USERNAME_RE } from '@/features/auth/schemas'
import { errorMessage } from '@/lib/api/client'
import { useMe } from '@/lib/api/queries/auth'
import { usePublicConfig } from '@/lib/api/queries/config'
import { useUpdateMe } from '@/lib/api/queries/users'
import { useRemoveWallet, useWallets } from '@/lib/api/queries/wallets'
import type { Me } from '@/lib/api/types'
import { formatDate } from '@/lib/format'
import { applyApiErrors } from '@/lib/form-errors'
import { accountExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'

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
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            {opts.area ? (
              <Textarea rows={4} placeholder={opts.placeholder} {...field} value={String(field.value)} />
            ) : (
              <Input placeholder={opts.placeholder} {...field} value={String(field.value)} />
            )}
          </FormControl>
          {opts.description && <FormDescription>{opts.description}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  )

  return (
    <Form {...form}>
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        <div className="grid gap-5 sm:grid-cols-2">
          {text('display_name', 'Display name')}
          {text('username', 'Username', { description: 'Your public profile lives at /u/username.' })}
        </div>
        {text('bio', 'Bio', { area: true })}
        {text('avatar_url', 'Avatar URL', { placeholder: 'https://…' })}
        <div className="grid gap-5 sm:grid-cols-2">
          {text('skills', 'Skills', { description: 'Comma separated.' })}
          {text('interests', 'Interests', { description: 'Comma separated.' })}
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          {text('github_url', 'GitHub URL', { placeholder: 'https://github.com/you' })}
          {text('portfolio_url', 'Portfolio URL', { placeholder: 'https://…' })}
        </div>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">I use BountyFlow to…</legend>
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
        </fieldset>
        <FormErrorAlert message={formError} />
        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={update.isPending || !form.formState.isDirty}>
            {update.isPending && <LoaderCircle className="animate-spin" />} Save changes
          </Button>
          <Button asChild variant="outline">
            <Link to={`/u/${me.username}`}>
              View public profile <ExternalLink />
            </Link>
          </Button>
        </div>
      </form>
    </Form>
  )
}

function WalletsCard() {
  const query = useWallets()
  const remove = useRemoveWallet()
  const { data: config } = usePublicConfig()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Wallet className="size-4" aria-hidden /> Linked wallets
        </CardTitle>
        <CardDescription>
          Payouts go to a verified wallet. Connect Freighter, then choose “Verify ownership” to sign a
          one-time proof. Nothing is submitted to the network.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <WalletButton />
        <QueryView
          query={query}
          skeleton="app-profile-wallets"
          isEmpty={(d) => d.length === 0}
          empty={{
            icon: Wallet,
            title: 'No wallets linked',
            description: 'Verify a wallet to receive payouts and fund bounties.',
          }}
        >
          {(wallets) => (
            <ul className="space-y-3">
              {wallets.map((w) => (
                <li
                  key={w.id}
                  className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0 space-y-1.5">
                    <MonoValue
                      value={w.public_address}
                      label="wallet address"
                      href={accountExplorerUrl(config, w.public_address)}
                    />
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant="success">
                        <ShieldCheck aria-hidden /> Ownership verified by signature
                      </Badge>
                      {networkDisplayName(w.network)}, verified {formatDate(w.verified_at)}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    disabled={remove.isPending}
                    onClick={() =>
                      remove.mutate(w.id, {
                        onSuccess: () => toast.success('Wallet unlinked'),
                        onError: (e) => toast.error(errorMessage(e)),
                      })
                    }
                  >
                    <Trash2 /> Unlink
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </CardContent>
    </Card>
  )
}

export default function ProfilePage() {
  const { data: me, isPending } = useMe()
  if (isPending) return <LoadingState label="Loading profile" />
  if (!me) return <EmptyState title="Not signed in" />
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="Profile"
        description="How you appear to requesters and contributors. Everything here except wallets is self-reported."
      />
      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Public details</CardTitle>
          </CardHeader>
          <CardContent>
            <ProfileForm me={me} />
          </CardContent>
        </Card>
        <WalletsCard />
      </div>
    </div>
  )
}
