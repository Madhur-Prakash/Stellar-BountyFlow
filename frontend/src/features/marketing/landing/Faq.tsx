import { Plus } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { cn } from '@/lib/utils'

import { SECTION, SECTION_LEAD, SECTION_TITLE } from './SectionHeading'

const FAQS: { q: string; a: ReactNode }[] = [
  {
    q: 'Do I need crypto to use BountyFlow?',
    a: 'You can browse and apply without a wallet. To fund a bounty or receive a payout you need a Stellar wallet (we support Freighter). On Testnet, Friendbot gives you free test XLM.',
  },
  {
    q: 'Who holds the reward while work is in progress?',
    a: 'A Soroban smart contract on Stellar. The requester transfers reward × positions into escrow, and the contract only releases it as a payout, a refund, or per a dispute decision.',
  },
  {
    q: 'What does “Funded” mean on a bounty?',
    a: 'That the full required amount is confirmed in escrow on-chain. Partially funded or pending bounties are labelled differently, and we never call a bounty funded before the network confirms it.',
  },
  {
    q: 'Is this running on Stellar Mainnet?',
    a: 'This deployment runs on Stellar Testnet, where test XLM has no monetary value. Every transaction you review names its network before you sign, and your workspace shows it next to your wallet. A Mainnet deployment uses real XLM.',
  },
  {
    q: 'What happens if the requester and contributor disagree?',
    a: (
      <>
        Either party can raise a dispute. A moderator reviews the evidence and records a decision; if funds
        are in escrow, the arbiter wallet then signs the release or refund. See{' '}
        <Link to="/guide#disputes" className="text-primary-emphasis underline underline-offset-4">
          disputes in the guide
        </Link>
        .
      </>
    ),
  },
  {
    q: 'Does BountyFlow charge fees?',
    a: (
      <>
        Stellar network fees apply to each transaction and are shown before you sign. See{' '}
        <Link to="/guide#fees" className="text-primary-emphasis underline underline-offset-4">
          fees
        </Link>{' '}
        for the current policy of this deployment.
      </>
    ),
  },
  {
    q: 'Can BountyFlow access my wallet or move my funds?',
    a: 'No. BountyFlow only asks Freighter to sign specific transactions you review first. It never sees your secret key and cannot move funds without your signature.',
  },
]

/** Questions on the right in hairline rows with a plus that turns into a cross; the heading holds the left. */
export function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-title" className={SECTION}>
      <PageContainer>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:gap-16">
          <div className="lg:sticky lg:top-28 lg:self-start">
            <h2 id="faq-title" className={SECTION_TITLE}>
              Common questions
            </h2>
            <p className={cn('mt-4', SECTION_LEAD)}>
              More detail lives in the{' '}
              <Link to="/guide" className="text-primary-emphasis underline underline-offset-4">
                guide
              </Link>
              .
            </p>
          </div>
          <Accordion type="single" collapsible className="border-t">
            {FAQS.map((f, i) => (
              <AccordionItem key={f.q} value={`q-${i}`} className="border-b not-last:border-b">
                <AccordionTrigger className="min-h-18 items-center gap-6 rounded-none py-5 text-left text-[1.0625rem] font-medium hover:no-underline **:data-[slot=accordion-trigger-icon]:hidden! sm:text-lg">
                  {f.q}
                  <Plus
                    aria-hidden
                    className="ml-auto size-5 shrink-0 text-muted-foreground transition-transform duration-300 group-aria-expanded/accordion-trigger:rotate-45 group-aria-expanded/accordion-trigger:text-foreground"
                  />
                </AccordionTrigger>
                <AccordionContent className="max-w-prose pb-6 text-[0.9375rem] leading-relaxed text-muted-foreground">
                  {f.a}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </PageContainer>
    </section>
  )
}
