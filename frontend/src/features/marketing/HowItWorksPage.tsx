import { Search } from 'lucide-react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { SplitHeading } from '@/components/motion/SplitHeading'
import { Button } from '@/components/ui/button'

import { EscrowExplainer } from './landing/EscrowExplainer'
import { HowItWorks } from './landing/HowItWorks'

export default function HowItWorksPage() {
  return (
    <>
      <PageContainer className="pt-14 pb-16 sm:pt-20 sm:pb-20">
        <SplitHeading
          as="h1"
          trigger="load"
          expand
          className="font-display max-w-4xl text-[clamp(2.6rem,6vw,4.75rem)] leading-[0.98] tracking-[-0.02em]"
        >
          From posted task to verified payout
        </SplitHeading>
        <p className="mt-4 max-w-2xl text-lg text-muted-foreground">
          Every bounty follows the same lifecycle. The difference from a regular job board is that the reward
          is locked in a smart contract before work begins, and every movement of money leaves a public
          record.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild>
            <Link to="/bounties">
              <Search /> Browse bounties
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/guide">Read the guide</Link>
          </Button>
        </div>
      </PageContainer>
      <HowItWorks />
      <EscrowExplainer />
    </>
  )
}
