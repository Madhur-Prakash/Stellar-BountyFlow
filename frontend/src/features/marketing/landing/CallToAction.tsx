import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'

/** Closing call to action: one quiet panel, not a billboard. */
export function CallToAction() {
  return (
    <section aria-labelledby="cta-title" className="pt-4 pb-20 sm:pb-24">
      <PageContainer>
        <div className="relative isolate overflow-hidden rounded-2xl border bg-card px-6 py-10 shadow-soft sm:px-10 sm:py-12">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(50%_80%_at_100%_0%,color-mix(in_oklab,var(--primary)_8%,transparent),transparent)]"
          />
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="max-w-xl">
              <h2 id="cta-title" className="font-display text-[1.625rem] leading-tight sm:text-[1.875rem]">
                Have a task that needs doing?
              </h2>
              <p className="mt-2 text-[0.9375rem] text-muted-foreground">
                Posting takes a few minutes. You fund it from your own wallet when you are ready.
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Button asChild size="lg">
                <Link to="/app/bounties/create">Post a bounty</Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link to="/bounties">Browse bounties</Link>
              </Button>
            </div>
          </div>
        </div>
      </PageContainer>
    </section>
  )
}
