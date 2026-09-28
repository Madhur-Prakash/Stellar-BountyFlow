import { Link } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyCardSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageContainer } from '@/components/layout/PageContainer'
import { DragRail } from '@/components/motion/DragRail'
import { Button } from '@/components/ui/button'
import { useFeaturedBounties } from '@/lib/api/queries/bounties'

function RailFallback() {
  return (
    <div className="flex gap-4 overflow-hidden" aria-hidden>
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="w-[19rem] shrink-0 sm:w-[21rem]">
          <BountyCardSkeleton />
        </div>
      ))}
    </div>
  )
}

/** Featured open bounties on a rail you can grab and throw (arrows and keyboard work too). */
export function OpenBountiesRail() {
  const { data, isPending, isError, error, refetch } = useFeaturedBounties()

  return (
    <section aria-labelledby="open-bounties-title" className="overflow-hidden border-b py-16 sm:py-24">
      <PageContainer>
        <div className="flex flex-col items-start gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div className="max-w-2xl">
            <h2
              id="open-bounties-title"
              className="font-display text-[2.25rem] leading-[1.02] sm:text-[3rem]"
            >
              Open bounties
            </h2>
            <p className="mt-4 text-[1.0625rem] leading-relaxed text-muted-foreground">
              Work that is taking applications now. Check the funding tag: green means the reward is already
              locked in escrow.
            </p>
          </div>
          <Button asChild variant="outline" className="shrink-0">
            <Link to="/bounties">See all bounties</Link>
          </Button>
        </div>

        <div className="mt-10">
          {isError ? (
            <ErrorState error={error} title="Open bounties could not be loaded" onRetry={() => refetch()} />
          ) : !isPending && data.length === 0 ? (
            <div className="rounded-xl border border-dashed px-6 py-12 text-center">
              <p className="font-medium">No open bounties right now.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Post the first one: describe the work, set a reward, and fund it from your wallet.
              </p>
              <Button asChild size="sm" className="mt-4">
                <Link to="/app/bounties/create">Post a bounty</Link>
              </Button>
            </div>
          ) : (
            <Bones name="landing-open-bounties" loading={isPending} fallback={<RailFallback />}>
              {data && (
                <DragRail label="Open bounties" itemClassName="w-[19rem] sm:w-[21rem]">
                  {data.map((b) => (
                    <BountyCard key={b.id} bounty={b} className="h-full" />
                  ))}
                </DragRail>
              )}
            </Bones>
          )}
        </div>
      </PageContainer>
    </section>
  )
}
