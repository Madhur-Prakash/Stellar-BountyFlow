import { PageContainer } from '@/components/layout/PageContainer'
import { Reveal } from '@/components/motion/Reveal'

import { SectionHeading } from './SectionHeading'

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

function Column({ id, title, points }: { id: string; title: string; points: Point[] }) {
  return (
    <div>
      <h3 id={id} className="text-lg font-semibold">
        {title}
      </h3>
      <Reveal as="dl" aria-labelledby={id} className="mt-4 divide-y border-y">
        {points.map((p) => (
          <div key={p.title} className="py-4">
            <dt className="font-medium">{p.title}</dt>
            <dd className="mt-1 text-[0.9375rem] leading-relaxed text-muted-foreground">{p.text}</dd>
          </div>
        ))}
      </Reveal>
    </div>
  )
}

export function Benefits() {
  return (
    <section aria-labelledby="benefits-title" className="border-b py-20 sm:py-24">
      <PageContainer>
        <SectionHeading id="benefits-title" title="Why teams and contributors use it" />
        <div className="mt-10 grid gap-12 md:grid-cols-2 md:gap-16">
          <Column id="benefits-requesters" title="For people posting work" points={REQUESTERS} />
          <Column id="benefits-contributors" title="For people doing the work" points={CONTRIBUTORS} />
        </div>
      </PageContainer>
    </section>
  )
}
