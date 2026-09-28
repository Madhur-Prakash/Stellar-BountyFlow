import { Check, Circle, LoaderCircle } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { WalletButton } from '@/components/chain/WalletButton'
import { EmailNotVerifiedNotice } from '@/components/common/EmailNotVerifiedNotice'
import { LoadingState } from '@/components/layout/LoadingState'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
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

function StepMarker({ n, done }: { n: number; done: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums',
        done ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-muted-foreground',
      )}
    >
      {done ? <Check className="size-3.5" strokeWidth={3} /> : n}
    </span>
  )
}

/** One onboarding step: numbered header, content aligned under the title, optional footer for its action. */
function StepCard({
  n,
  title,
  description,
  done,
  footer,
  children,
}: {
  n: number
  title: string
  description: ReactNode
  done: boolean
  footer?: ReactNode
  children?: ReactNode
}) {
  return (
    <Card className="gap-0">
      <CardHeader className={children ? 'pb-4' : undefined}>
        <div className="flex min-w-0 items-start gap-3">
          <StepMarker n={n} done={done} />
          <div className="min-w-0 space-y-1 pt-0.5">
            <CardTitle>
              <h2>{title}</h2>
            </CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
        </div>
        {done && (
          <CardAction>
            <Badge variant="muted">
              <Check aria-hidden /> Done
            </Badge>
          </CardAction>
        )}
      </CardHeader>
      {children && <CardContent className={cn('sm:pl-15', footer && 'pb-5')}>{children}</CardContent>}
      {footer && <CardFooter className="justify-end gap-3 px-5 py-3">{footer}</CardFooter>}
    </Card>
  )
}

function ProfileStep({ me, n }: { me: Me; n: number }) {
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

  const option =
    'flex min-h-10 items-center gap-3 rounded-lg border px-3 py-2 font-normal transition-colors hover:bg-surface/60 has-data-[state=checked]:border-primary/40 has-data-[state=checked]:bg-primary/5'

  return (
    <StepCard
      n={n}
      title="About you"
      description="Tailors your dashboard and recommendations."
      done={me.onboarding.role_selected && me.onboarding.profile_completed}
      footer={
        <Button
          onClick={save}
          disabled={update.isPending || (!request && !contribute) || tooLong || tooManySkills}
        >
          {update.isPending && <LoaderCircle className="animate-spin" />} Save profile
        </Button>
      }
    >
      <div className="space-y-5">
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">I want to…</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            <Label className={option}>
              <Checkbox checked={request} onCheckedChange={(v) => setRequest(v === true)} /> Post bounties and
              pay for work
            </Label>
            <Label className={option}>
              <Checkbox checked={contribute} onCheckedChange={(v) => setContribute(v === true)} /> Find work
              and earn rewards
            </Label>
          </div>
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
            className={cn('text-[0.8125rem] text-muted-foreground', tooLong && 'text-destructive')}
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
            className={cn('text-[0.8125rem] text-muted-foreground', tooManySkills && 'text-destructive')}
          >
            {tooManySkills
              ? 'Add at most 15 skills.'
              : 'Comma separated, up to 15. Shown on your public profile as self-reported.'}
          </p>
        </div>
      </div>
    </StepCard>
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
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Set up your account"
        description={`${done} of ${STEPS.length} steps done. Everything except email verification can be finished later.`}
      />

      <ol className="mb-8 grid gap-2.5 sm:grid-cols-5 sm:gap-2" aria-label="Onboarding progress">
        {STEPS.map((s) => (
          <li key={s.key} data-done={o[s.key] || undefined} className="min-w-0">
            <span
              aria-hidden
              className={cn('hidden h-1 rounded-full sm:block', o[s.key] ? 'bg-primary' : 'bg-border')}
            />
            <span className="flex items-start gap-2 text-xs sm:mt-2.5">
              {o[s.key] ? (
                <Check className="mt-px size-3.5 shrink-0 text-primary" strokeWidth={2.5} aria-hidden />
              ) : (
                <Circle className="mt-px size-3.5 shrink-0 text-muted-foreground/60" aria-hidden />
              )}
              <span className={o[s.key] ? 'text-foreground' : 'text-muted-foreground'}>
                {s.label}
                <span className="sr-only">{o[s.key] ? ' (done)' : ' (to do)'}</span>
              </span>
            </span>
          </li>
        ))}
      </ol>

      <div className="space-y-4">
        <StepCard
          n={1}
          title="Verify your email"
          description={
            me.email_verified
              ? 'Your email address is verified.'
              : 'Needed before you can publish bounties or receive payouts.'
          }
          done={o.email_verified}
        >
          {!me.email_verified && <EmailNotVerifiedNotice action="publish bounties and receive payouts" />}
        </StepCard>

        <ProfileStep me={me} n={2} />

        <StepCard
          n={3}
          title="Link a wallet"
          description={
            <>
              Payouts only go to a verified wallet. Connect Freighter, then choose “Verify ownership” in the
              wallet menu. New to Freighter? Read the{' '}
              <Link to="/guide#wallets" className="text-foreground underline underline-offset-4">
                wallet guide
              </Link>
              .
            </>
          }
          done={o.wallet_connected}
        >
          <WalletButton />
        </StepCard>

        <StepCard
          n={4}
          title="Get started"
          description="Post your first bounty or apply to one."
          done={o.first_action_taken}
        >
          <div className="flex flex-wrap gap-3">
            <Button asChild variant="outline">
              <Link to="/app/bounties/create">Post a bounty</Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/bounties">Browse bounties</Link>
            </Button>
          </div>
        </StepCard>

        <div className="flex flex-col-reverse gap-3 pt-4 sm:flex-row sm:justify-end">
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
