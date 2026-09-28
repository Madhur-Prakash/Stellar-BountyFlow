import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { SplitHeading } from '@/components/motion/SplitHeading'
import { Button } from '@/components/ui/button'

import { Benefits } from './landing/Benefits'
import { EscrowExplainer } from './landing/EscrowExplainer'
import { Faq } from './landing/Faq'
import { Hero } from './landing/Hero'
import { HowItWorks } from './landing/HowItWorks'
import { OpenBountiesRail } from './landing/OpenBountiesRail'
import { PlatformStats } from './landing/PlatformStats'

export default function LandingPage() {
  return (
    <>
      <Hero />
      <OpenBountiesRail />
      <HowItWorks />
      <EscrowExplainer />
      <PlatformStats />
      <Benefits />
      <Faq />
      <section aria-labelledby="cta-title" className="py-24 sm:py-32">
        <PageContainer>
          <SplitHeading
            id="cta-title"
            expand
            className="font-display max-w-5xl text-[clamp(2.75rem,7vw,6.5rem)] leading-[0.95] tracking-[-0.02em]"
          >
            Have a task that needs doing?
          </SplitHeading>
          <div className="mt-10 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <p className="max-w-xl text-lg text-muted-foreground">
              Posting takes a few minutes. You fund it from your own wallet when you are ready.
            </p>
            <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
              <Button asChild size="lg">
                <Link to="/app/bounties/create">Post a bounty</Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link to="/bounties">Browse bounties</Link>
              </Button>
            </div>
          </div>
        </PageContainer>
      </section>
    </>
  )
}
