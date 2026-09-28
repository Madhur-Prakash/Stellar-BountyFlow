import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'

import { SECTION, SectionHeading } from './SectionHeading'

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

export function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-title" className={SECTION}>
      <PageContainer>
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] lg:gap-12">
          <SectionHeading
            className="self-start sm:items-start"
            id="faq-title"
            title="Common questions"
            description={
              <>
                More detail lives in the{' '}
                <Link to="/guide" className="text-primary-emphasis underline underline-offset-4">
                  guide
                </Link>
                .
              </>
            }
          />
          <Accordion
            type="single"
            collapsible
            className="divide-y rounded-xl border bg-card px-5 shadow-soft"
          >
            {FAQS.map((f, i) => (
              <AccordionItem key={f.q} value={`q-${i}`} className="border-b-0">
                <AccordionTrigger className="min-h-14 text-left text-[0.9375rem] font-medium">
                  {f.q}
                </AccordionTrigger>
                <AccordionContent className="max-w-prose text-sm leading-relaxed text-muted-foreground">
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
