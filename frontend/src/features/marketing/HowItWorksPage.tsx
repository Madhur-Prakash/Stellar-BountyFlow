import { BookOpen, Search } from 'lucide-react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'

import { CallToAction } from './landing/CallToAction'
import { EscrowExplainer } from './landing/EscrowExplainer'
import { HowItWorks } from './landing/HowItWorks'

export default function HowItWorksPage() {
  return (
    <>
      <section className="relative isolate overflow-hidden border-b">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-80 bg-[radial-gradient(60%_70%_at_50%_0%,color-mix(in_oklab,var(--primary)_8%,transparent),transparent)]"
        />
        <PageContainer className="py-14 sm:py-20">
          <h1 className="font-display max-w-3xl text-[2.125rem] leading-[1.1] sm:text-[2.625rem]">
            From posted task to verified payout
          </h1>
          <p className="mt-4 max-w-2xl text-[1.0625rem] leading-relaxed text-muted-foreground">
            Every bounty follows the same lifecycle. The difference from a regular job board is that the
            reward is locked in a smart contract before work begins, and every movement of money leaves a
            public record.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild>
              <Link to="/bounties">
                <Search /> Browse bounties
              </Link>
            </Button>
            <Button asChild variant="outline">
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
