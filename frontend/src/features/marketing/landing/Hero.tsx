import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import { Scramble } from '@/components/motion/Scramble'
import { SplitHeading } from '@/components/motion/SplitHeading'
import { Button } from '@/components/ui/button'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { hasFinePointer, motionAllowed } from '@/hooks/useReducedMotion'
import { useBounties } from '@/lib/api/queries/bounties'
import { usePublicConfig } from '@/lib/api/queries/config'
import { gsap, useGSAP } from '@/lib/gsap'
import { addAmounts, formatAmount } from '@/lib/money'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'

import { RewardPool } from './RewardPool'

const POOL_QUERY = { sort: 'reward_high', page_size: 12 } as const

/** The window's inner height, kept current on resize. */
function useViewportHeight(): number {
  const [height, setHeight] = useState(() => (typeof window === 'undefined' ? 900 : window.innerHeight))
  useEffect(() => {
    const onResize = () => setHeight(window.innerHeight)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return height
}

function ContractLine() {
  const { data } = usePublicConfig()
  if (!data?.contract_id) return null
  const href = data.contract_explorer_url ?? contractExplorerUrl(data, data.contract_id)
  const id = `${data.contract_id.slice(0, 6)}…${data.contract_id.slice(-6)}`
  return (
    <p className="text-sm text-muted-foreground">
      Escrow contract on {networkDisplayName(data.network, data.blockchain_mode)}:{' '}
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Escrow contract ${data.contract_id} on the Stellar explorer`}
          className="text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground"
        >
          <Scramble text={id} className="text-[0.8125rem]" />
        </a>
      ) : (
        <Scramble text={id} className="text-[0.8125rem] text-foreground" />
      )}
    </p>
  )
}

/** What is open right now, from the same data as the coins: count, total rewards, and how to use the floor. */
function LiveSummary({ query }: { query: ReturnType<typeof useBounties> }) {
  const { data, isPending, isError, refetch } = query
  if (isPending) return <p className="text-sm text-muted-foreground">Loading open bounties…</p>
  if (isError) {
    return (
      <p className="text-sm text-muted-foreground" role="alert">
        Open bounties could not be loaded.{' '}
        <button
          type="button"
          onClick={() => refetch()}
          className="text-foreground underline underline-offset-4"
        >
          Try again
        </button>
      </p>
    )
  }
  if (data.items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No open bounties right now.{' '}
        <Link to="/app/bounties/create" className="text-foreground underline underline-offset-4">
          Post the first one
        </Link>
      </p>
    )
  }
  const total = formatAmount(addAmounts(...data.items.map((b) => b.total_reward)), { maxDecimals: 0 })
  const complete = data.total <= data.items.length
  return (
    <p className="text-sm leading-relaxed text-muted-foreground">
      <span className="font-medium text-foreground">
        {data.total} open {data.total === 1 ? 'bounty' : 'bounties'}
      </span>
      {complete ? (
        <>
          {' '}
          with <span className="font-medium text-foreground">{total} XLM</span> in rewards.
        </>
      ) : (
        <>; the {data.items.length} largest rewards are below.</>
      )}{' '}
      {motionAllowed() && hasFinePointer()
        ? 'Pick up a coin and throw it, or click one to open the bounty.'
        : 'Each coin opens its bounty.'}{' '}
      <span className="whitespace-nowrap">
        <span className="mr-1 inline-block size-2.5 rounded-full bg-success align-[-1px]" aria-hidden />
        Green means funded in escrow.
      </span>
    </p>
  )
}

export function Hero() {
  const scope = useRef<HTMLElement>(null)
  const query = useBounties(POOL_QUERY)
  const wide = useMediaQuery('(min-width: 1024px)')
  const medium = useMediaQuery('(min-width: 640px)')
  const viewportHeight = useViewportHeight()
  // Height of the band along the bottom of the hero where the coins come to rest: about a third of the screen on
  // desktop, so the headline, the actions and the coins all fit on the first screen.
  const band = wide ? Math.max(200, Math.min(300, Math.round(viewportHeight * 0.32))) : medium ? 240 : 200

  useGSAP(
    () => {
      if (!motionAllowed()) return
      gsap.from('[data-hero-fade]', { autoAlpha: 0, y: 18, duration: 0.8, stagger: 0.1, delay: 0.5 })
    },
    { scope },
  )

  return (
    <section
      ref={scope}
      aria-labelledby="hero-title"
      className="relative isolate flex min-h-[calc(100svh-4rem)] flex-col overflow-hidden border-b"
    >
      <div
        className="mx-auto grid w-full max-w-384 flex-1 grid-cols-1 content-center gap-10 px-4 pt-12 sm:px-6 sm:pt-16 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:items-end lg:gap-16 lg:px-8 lg:pt-10 2xl:px-12"
        style={{ paddingBottom: band + 32 }}
      >
        <SplitHeading
          as="h1"
          id="hero-title"
          trigger="load"
          expand
          className="font-display text-[clamp(2.9rem,6vw,6.25rem)] leading-[0.92] tracking-tight"
        >
          Work gets done. Rewards move transparently.
        </SplitHeading>

        <div className="min-w-0 space-y-7 lg:pb-3">
          <p data-hero-fade className="max-w-xl text-lg leading-relaxed text-muted-foreground">
            Post a task with a reward in XLM. The reward is locked in a Soroban escrow contract before anyone
            starts, and it is released to the contributor when you approve the work.
          </p>
          <div data-hero-fade className="flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg" className="sm:min-w-40">
              <Link to="/bounties">Browse bounties</Link>
            </Button>
            <Button asChild size="lg" variant="outline" className="sm:min-w-40">
              <Link to="/app/bounties/create">Post a bounty</Link>
            </Button>
          </div>
          <div data-hero-fade className="max-w-xl space-y-2">
            <LiveSummary query={query} />
            <ContractLine />
          </div>
        </div>
      </div>

      {/* The floor the coins rest on. */}
      <span aria-hidden className="absolute inset-x-0 bottom-0 h-px bg-border" />
      {query.data && query.data.items.length > 0 && <RewardPool bounties={query.data.items} band={band} />}
    </section>
  )
}
