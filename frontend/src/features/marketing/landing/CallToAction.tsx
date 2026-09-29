import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Atmosphere } from '@/components/marketing/Atmosphere'
import { Scene } from '@/components/three/Scene'
import { Button } from '@/components/ui/button'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/utils'

import { SECTION_LEAD, SECTION_TITLE } from './SectionHeading'

/** Closing call to action: the ledger field rolling under a short line and the two actions. */
export function CallToAction() {
  const wide = useMediaQuery('(min-width: 1024px)')
  return (
    <section aria-labelledby="cta-title" className="pt-8 pb-20 sm:pb-28">
      <PageContainer>
        <Atmosphere
          tone="night"
          className="px-6 pt-16 pb-20 text-center sm:px-10 sm:pt-24 sm:pb-40"
          backdrop={
            wide && (
              <Scene
                name="ledger"
                className="absolute inset-x-0 bottom-0 h-3/5 animate-in mask-[linear-gradient(to_top,black_45%,transparent)] duration-1000 fade-in-0"
              />
            )
          }
        >
          <h2 id="cta-title" className={cn('mx-auto max-w-3xl', SECTION_TITLE, 'lg:text-[3.25rem]')}>
            Have a task that needs doing?
          </h2>
          <p className={cn('mx-auto mt-4 max-w-xl', SECTION_LEAD)}>
            Posting takes a few minutes. You fund it from your own wallet when you are ready.
          </p>
          {/* data-primary-action: the floating feedback button lifts itself clear of these two, which run the
              full width on a phone. */}
          <div className="mt-9 flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
            <Button asChild variant="inverse" size="pill" data-primary-action>
              <Link to="/app/bounties/create">Post a bounty</Link>
            </Button>
            <Button asChild variant="outline" size="pill" data-primary-action>
              <Link to="/bounties">Browse bounties</Link>
            </Button>
          </div>
        </Atmosphere>
      </PageContainer>
    </section>
  )
}
