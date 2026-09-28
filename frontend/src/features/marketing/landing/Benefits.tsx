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

function Column({
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
    <div className="rounded-xl border bg-card p-6 shadow-soft">
      <div className="flex items-center gap-3">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-4" aria-hidden />
        </span>
        <h3 id={id} className="text-[0.9375rem] font-semibold">
          {title}
        </h3>
      </div>
      <dl aria-labelledby={id} className="mt-5 space-y-4">
        {points.map((p) => (
          <div key={p.title}>
            <dt className="flex items-center gap-2.5 text-sm font-medium">
              <Check className="size-4 shrink-0 text-success" aria-hidden />
              {p.title}
            </dt>
            <dd className="mt-0.5 pl-6.5 text-sm leading-relaxed text-muted-foreground">{p.text}</dd>
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
        <SectionHeading id="benefits-title" title="Why teams and contributors use it" />
        <div className="mt-8 grid gap-6 md:grid-cols-2">
          <Column
            id="benefits-requesters"
            title="For people posting work"
            icon={BriefcaseBusiness}
            points={REQUESTERS}
          />
          <Column
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
