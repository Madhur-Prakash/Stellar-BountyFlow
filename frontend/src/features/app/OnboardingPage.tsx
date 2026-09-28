import { Check, CircleDashed, LoaderCircle } from 'lucide-react'
import { useId, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { WalletButton } from '@/components/chain/WalletButton'
import { EmailNotVerifiedNotice } from '@/components/common/EmailNotVerifiedNotice'
import { LoadingState } from '@/components/layout/LoadingState'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { useMe } from '@/lib/api/queries/auth'
import { useCompleteOnboarding, useUpdateMe } from '@/lib/api/queries/users'
import type { Me, OnboardingState } from '@/lib/api/types'
import { safeNext } from '@/lib/auth-redirect'
import { cn } from '@/lib/utils'

const STEPS: { key: keyof Omit<OnboardingState, 'completed'>; label: string }[] = [
  { key: 'email_verified', label: 'Verify your email' },
  { key: 'role_selected', label: 'Choose how you’ll use BountyFlow' },
  { key: 'profile_completed', label: 'Add a bio and skills' },
  { key: 'wallet_connected', label: 'Link a wallet' },
  { key: 'first_action_taken', label: 'Post or apply to a bounty' },
]

const BIO_MAX = 1000

function ProfileStep({ me }: { me: Me }) {
  const update = useUpdateMe()
  const ids = { bio: useId(), skills: useId() }
  const [request, setRequest] = useState(me.wants_to_request)
  const [contribute, setContribute] = useState(me.wants_to_contribute)
  const [bio, setBio] = useState(me.bio ?? '')
  const [skills, setSkills] = useState(me.skills.join(', '))
  const tooLong = bio.trim().length > BIO_MAX
  const skillList = Array.from(
    new Set(
      skills
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
    ),
  )
  const tooManySkills = skillList.length > 15

  const save = () =>
    update.mutate(
      {
        wants_to_request: request,
        wants_to_contribute: contribute,
        bio: bio.trim() || null,
        skills: skillList,
      },
      { onSuccess: () => toast.success('Profile saved'), onError: (e) => toast.error(errorMessage(e)) },
    )

  return (
    <Card>
      <CardHeader>
        <CardTitle>About you</CardTitle>
        <CardDescription>
          This tailors your dashboard and recommendations. You can change it any time.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">I want to…</legend>
          <Label className="flex min-h-10 items-center gap-3 font-normal">
            <Checkbox checked={request} onCheckedChange={(v) => setRequest(v === true)} /> Post bounties and
            pay for work
          </Label>
          <Label className="flex min-h-10 items-center gap-3 font-normal">
            <Checkbox checked={contribute} onCheckedChange={(v) => setContribute(v === true)} /> Find work and
            earn rewards
          </Label>
        </fieldset>
        <div className="space-y-2">
          <Label htmlFor={ids.bio}>Short bio</Label>
          <Textarea
            id={ids.bio}
            rows={3}
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder="What you build, what you’re good at, what you’re looking for."
            aria-invalid={tooLong}
            aria-describedby={`${ids.bio}-hint`}
          />
          <p
            id={`${ids.bio}-hint`}
            className={cn('text-xs text-muted-foreground', tooLong && 'text-destructive')}
          >
            {tooLong ? `Keep it under ${BIO_MAX} characters.` : 'Shown on your public profile.'}
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor={ids.skills}>Skills</Label>
          <Input
            id={ids.skills}
            value={skills}
            onChange={(e) => setSkills(e.target.value)}
            placeholder="rust, soroban, react, technical writing"
            aria-describedby={`${ids.skills}-hint`}
            aria-invalid={tooManySkills}
          />
          <p
            id={`${ids.skills}-hint`}
            className={cn('text-xs text-muted-foreground', tooManySkills && 'text-destructive')}
          >
            {tooManySkills
              ? 'Add at most 15 skills.'
              : 'Comma separated, up to 15. Shown on your public profile as self-reported.'}
          </p>
        </div>
        <Button
          onClick={save}
          disabled={update.isPending || (!request && !contribute) || tooLong || tooManySkills}
        >
          {update.isPending && <LoaderCircle className="animate-spin" />} Save profile
        </Button>
      </CardContent>
    </Card>
  )
}

export default function OnboardingPage() {
  const { data: me, isPending } = useMe()
  const complete = useCompleteOnboarding()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next')) ?? '/app'

  if (isPending || !me) return <LoadingState label="Loading your account" />
  const o = me.onboarding
  const done = STEPS.filter((s) => o[s.key]).length

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Set up your account"
        description={`${done} of ${STEPS.length} steps done. Everything except email verification can be finished later.`}
      />

      <ol className="mb-8 grid gap-2 sm:grid-cols-2 lg:grid-cols-5" aria-label="Onboarding progress">
        {STEPS.map((s) => (
          <li
            key={s.key}
            data-done={o[s.key] || undefined}
            className={cn(
              'flex items-start gap-2 rounded-lg border p-3 text-xs',
              o[s.key] ? 'border-success/30 bg-success/5' : 'bg-card',
            )}
          >
            {o[s.key] ? (
              <Check className="size-4 shrink-0 text-success" aria-hidden />
            ) : (
              <CircleDashed className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
            <span>
              {s.label}
              <span className="sr-only">{o[s.key] ? ' (done)' : ' (to do)'}</span>
            </span>
          </li>
        ))}
      </ol>

      <div className="space-y-6">
        {!me.email_verified && <EmailNotVerifiedNotice action="publish bounties and receive payouts" />}

        <ProfileStep me={me} />

        <Card>
          <CardHeader>
            <CardTitle>Wallet</CardTitle>
            <CardDescription>
              Connect Freighter and choose “Verify ownership” to prove the address is yours. Payouts can only
              go to a verified wallet. New to Freighter? Read the{' '}
              <Link to="/guide#wallets" className="underline underline-offset-4">
                wallet guide
              </Link>
              .
            </CardDescription>
          </CardHeader>
          <CardContent>
            <WalletButton />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Get started</CardTitle>
            <CardDescription>Post your first bounty or apply to one.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Button asChild variant="outline">
              <Link to="/app/bounties/create">Post a bounty</Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/bounties">Browse bounties</Link>
            </Button>
          </CardContent>
        </Card>

        <div className="flex flex-col-reverse gap-3 border-t pt-6 sm:flex-row sm:justify-end">
          <Button asChild variant="ghost">
            <Link to={next}>Skip for now</Link>
          </Button>
          <Button
            disabled={complete.isPending}
            onClick={() =>
              complete.mutate(undefined, {
                onSuccess: () => {
                  toast.success('You’re all set')
                  navigate(next, { replace: true })
                },
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            {complete.isPending && <LoaderCircle className="animate-spin" />} Finish onboarding
          </Button>
        </div>
      </div>
    </div>
  )
}
