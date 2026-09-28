import { BriefcaseBusiness, Check, UserRound, type LucideIcon } from 'lucide-react'

import { PageContainer } from '@/components/layout/PageContainer'

import { SECTION, SectionHeading } from './SectionHeading'

type Point = { title: string; text: string }

const REQUESTERS: Point[] = [
  {
    title: 'Pay for accepted results',
    text: 'Money leaves escrow only when you approve a submission against your own criteria.',
  },
  {
    title: 'Applicants who expect to deliver',
    text: 'Contributors can see the reward is already funded, so the people who apply take it seriously.',
  },
  {
    title: 'One place to review',
    text: 'Applications, submissions, revisions, and payouts live in one workspace with a full history.',
  },
  {
    title: 'A refund path',
    text: 'Unassigned or cancelled work is refunded from the contract instead of chased by email.',
  },
]

const CONTRIBUTORS: Point[] = [
  {
    title: 'See the money first',
    text: '“Funded in escrow” means the reward is confirmed on Stellar, not promised.',
  },
  {
    title: 'Paid straight to your wallet',
    text: 'Payouts go from the contract to your verified address, with a hash for your records.',
  },
  {
    title: 'A record you can share',
    text: 'Completed bounties and confirmed payouts build a public profile you can link to.',
  },
  {
    title: 'Your keys stay yours',
    text: 'You sign in Freighter. BountyFlow never asks for a secret key or recovery phrase.',
  },
]

/** One side of the grid: a header cell, then its four points as cells sharing hairline dividers. */
function Side({
  id,
  title,
  icon: Icon,
  points,
}: {
  id: string
  title: string
  icon: LucideIcon
  points: Point[]
}) {
  return (
    <div className="grid gap-px bg-border">
      <div className="flex items-center gap-3 bg-card px-6 py-5 sm:px-7">
        <Icon className="size-4 shrink-0 text-primary-emphasis" aria-hidden />
        <h3 id={id} className="text-base font-medium">
          {title}
        </h3>
      </div>
      <dl aria-labelledby={id} className="grid gap-px sm:grid-cols-2">
        {points.map((p) => (
          <div key={p.title} className="bg-card px-6 py-7 sm:px-7 sm:py-8">
            <dt className="flex items-start gap-2.5 text-[0.9375rem] leading-snug font-medium">
              <Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
              {p.title}
            </dt>
            <dd className="mt-2 pl-6.5 text-[0.9375rem] leading-relaxed text-muted-foreground">{p.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function Benefits() {
  return (
    <section aria-labelledby="benefits-title" className={SECTION}>
      <PageContainer>
        <SectionHeading
          id="benefits-title"
          label="Both sides"
          title="Why teams and contributors use it"
          description="What changes when the reward is in escrow before the work starts."
        />
        <div className="mt-10 grid gap-px overflow-hidden rounded-2xl border bg-border lg:grid-cols-2">
          <Side
            id="benefits-requesters"
            title="For people posting work"
            icon={BriefcaseBusiness}
            points={REQUESTERS}
          />
          <Side
            id="benefits-contributors"
            title="For people doing the work"
            icon={UserRound}
            points={CONTRIBUTORS}
          />
        </div>
      </PageContainer>
    </section>
  )
}
