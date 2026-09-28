import { BookOpen, Search } from 'lucide-react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { MonoLabel } from '@/components/marketing'
import { Button } from '@/components/ui/button'

import { CallToAction } from './landing/CallToAction'
import { EscrowExplainer } from './landing/EscrowExplainer'
import { HowItWorks } from './landing/HowItWorks'

export default function HowItWorksPage() {
  return (
    <>
      <section aria-labelledby="how-page-title">
        <PageContainer className="flex flex-col items-center pt-16 pb-12 text-center sm:pt-28 sm:pb-16">
          <MonoLabel>How it works</MonoLabel>
          <h1
            id="how-page-title"
            className="mt-5 max-w-4xl text-[2.5rem] leading-[1.02] font-normal tracking-[-0.02em] sm:text-[3.75rem] lg:text-[4.5rem]"
          >
            From posted task to verified payout
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-[1.6] text-muted-foreground sm:text-xl">
            Every bounty follows the same lifecycle. The reward is locked in a smart contract before work
            begins, and every movement of money leaves a public record.
          </p>
          <div className="mt-10 flex flex-wrap justify-center gap-3">
            <Button asChild variant="inverse" size="pill">
              <Link to="/bounties">
                <Search /> Browse bounties
              </Link>
            </Button>
            <Button asChild variant="outline" size="pill">
              <Link to="/guide">
                <BookOpen /> Read the guide
              </Link>
            </Button>
          </div>
        </PageContainer>
      </section>
      <HowItWorks />
      <EscrowExplainer />
      <CallToAction />
    </>
  )
}
