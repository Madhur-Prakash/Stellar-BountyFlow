import { Code2, Globe, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router'

import { GithubMark } from '@/components/brand/GithubMark'
import { PageContainer } from '@/components/layout/PageContainer'
import { Reveal } from '@/components/motion/Reveal'
import { SplitHeading } from '@/components/motion/SplitHeading'
import { Button } from '@/components/ui/button'
import { SITE } from '@/lib/site'

const PRINCIPLES = [
  {
    icon: ShieldCheck,
    title: 'Money first, then work',
    text: 'Contributors shouldn’t have to wonder whether they’ll be paid. Escrow makes the reward visible before anyone starts.',
  },
  {
    icon: Globe,
    title: 'Verifiable over promised',
    text: 'Where a fact can be checked on Stellar, we link to it. Where it can’t, we label it as off-chain.',
  },
  {
    icon: Code2,
    title: 'Small, honest software',
    text: 'No invented metrics, testimonials, or partner logos. The numbers on this site come straight from the API.',
  },
]

export default function AboutPage() {
  return (
    <PageContainer className="py-14 sm:py-20">
      <div className="max-w-3xl">
        <SplitHeading
          as="h1"
          trigger="load"
          expand
          className="font-display text-[clamp(2.6rem,6vw,4.75rem)] leading-[0.98] tracking-[-0.02em]"
        >
          Why we built BountyFlow
        </SplitHeading>
        <div className="mt-6 space-y-4 text-lg text-muted-foreground">
          <p>
            Paid open work, like bug fixes, audits, docs, and design, usually runs on trust. A requester
            promises a reward and the contributor hopes it arrives. When it doesn’t, there’s little recourse.
          </p>
          <p>
            BountyFlow moves that promise into a Soroban smart contract on Stellar. Stellar’s low fees and
            fast finality make it practical to escrow even small rewards and pay them out the moment work is
            approved.
          </p>
          <p>
            BountyFlow currently runs on Stellar Testnet, where every escrow, payout and refund is a real
            contract call you can inspect on the explorer, with test XLM that has no monetary value.
          </p>
        </div>
      </div>

      <Reveal as="ul" className="mt-16 grid gap-8 md:grid-cols-3 md:gap-10">
        {PRINCIPLES.map(({ title, text }) => (
          <li key={title} className="border-t pt-5">
            <h2 className="font-medium">{title}</h2>
            <p className="mt-1.5 text-sm text-muted-foreground">{text}</p>
          </li>
        ))}
      </Reveal>

      <div className="mt-14 flex flex-wrap gap-3">
        <Button asChild>
          <Link to="/how-it-works">See how it works</Link>
        </Button>
        {SITE.githubUrl && (
          <Button asChild variant="outline">
            <a href={SITE.githubUrl} target="_blank" rel="noopener noreferrer nofollow">
              <GithubMark /> View the source
            </a>
          </Button>
        )}
      </div>
    </PageContainer>
  )
}
