import { BriefcaseBusiness, PenLine, UserRound, type LucideIcon } from 'lucide-react'

import { PageContainer } from '@/components/layout/PageContainer'
import { cn } from '@/lib/utils'

import { CONTRIBUTOR_STEPS, REQUESTER_STEPS, type Step } from './howItWorksData'
import { SECTION, SectionHeading } from './SectionHeading'

const TRACKS: { id: string; title: string; icon: LucideIcon; steps: readonly Step[] }[] = [
  { id: 'requester', title: 'When you post work', icon: BriefcaseBusiness, steps: REQUESTER_STEPS },
  { id: 'contributor', title: 'When you do the work', icon: UserRound, steps: CONTRIBUTOR_STEPS },
]

function Track({ id, title, icon: Icon, steps }: (typeof TRACKS)[number]) {
  const headingId = `track-${id}`
  return (
    <div className="rounded-xl border bg-card shadow-soft">
      <div className="flex items-center gap-3 border-b px-5 py-4">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-4" aria-hidden />
        </span>
        <h3 id={headingId} className="text-[0.9375rem] font-semibold">
          {title}
        </h3>
        <span className="ml-auto text-xs text-muted-foreground">{steps.length} steps</span>
      </div>
      <ol aria-labelledby={headingId} className="px-5 py-2">
        {steps.map((step, i) => (
          <li key={step.title} className="relative grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 py-3.5">
            {i < steps.length - 1 && (
              <span aria-hidden className="absolute top-11 bottom-0 left-3.25 w-px bg-border" />
            )}
            <span
              aria-hidden
              className="amount flex size-7 items-center justify-center rounded-full border bg-background text-xs"
            >
              {i + 1}
            </span>
            <div className="pt-0.5">
              <p className="text-sm font-medium">
                {step.title}
                {step.signed && (
                  <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs font-normal text-primary-emphasis">
                    <PenLine className="size-3" aria-hidden />
                    Signed in your wallet
                  </span>
                )}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** Both sides of a bounty, step by step. Only the steps marked as signed ask the wallet for anything. */
export function HowItWorks({ className }: { className?: string }) {
  return (
    <section id="how-it-works" aria-labelledby="how-title" className={cn(SECTION, className)}>
      <PageContainer>
        <SectionHeading
          id="how-title"
          title="How a bounty moves"
          description="The same bounty from both sides, from posting the work to the payout."
        />
        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          {TRACKS.map((t) => (
            <Track key={t.id} {...t} />
          ))}
        </div>
      </PageContainer>
    </section>
  )
}
