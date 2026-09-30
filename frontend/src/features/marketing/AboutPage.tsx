import { Check, ExternalLink, KeyRound, Scale, Search, ShieldCheck, X } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router'

import { PageBreadcrumbs } from '@/components/layout/PageBreadcrumbs'
import { PageContainer } from '@/components/layout/PageContainer'
import { AppWindow, Atmosphere, MonoLabel } from '@/components/marketing'
import { Scene } from '@/components/three/Scene'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { usePublicStats } from '@/lib/api/queries/analytics'
import { usePublicConfig } from '@/lib/api/queries/config'
import { formatNumber } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'

import { CallToAction } from './landing/CallToAction'
import { SectionHeading } from './landing/SectionHeading'

/**
 * The network drifts behind the headline and thins out to the right, where the argument is set, and towards
 * the band below. The ellipse keeps it off the display type itself, so nothing competes with the words.
 */
const HERO_SCENE_MASK: CSSProperties = {
  maskImage: [
    'linear-gradient(to bottom, black 56%, transparent 95%)',
    'linear-gradient(to right, black 34%, rgb(0 0 0 / 0.22) 70%, transparent 97%)',
    'radial-gradient(ellipse 30% 26% at 20% 56%, rgb(0 0 0 / 0.25), black 100%)',
  ].join(', '),
  maskComposite: 'intersect',
  WebkitMaskComposite: 'source-in',
}

const PRINCIPLES = [
  {
    icon: ShieldCheck,
    title: 'Money first, then work',
    text: 'The reward is in escrow before anyone starts, so contributors know they will be paid.',
  },
  {
    icon: Scale,
    title: 'Verifiable, not promised',
    text: 'Funding, payouts and refunds are Stellar transactions that anyone can look up.',
  },
  {
    icon: KeyRound,
    title: 'Your keys, your signature',
    text: 'BountyFlow never holds your keys. Every transfer is one you review and sign in your own wallet.',
  },
]

const DOES = [
  'Holds each reward in a Soroban escrow contract until the work is approved',
  'Pays contributors straight from the contract to their verified wallet',
  'Refunds cancelled or unassigned work back to the requester',
  'Links every funding, payout and refund to a public explorer',
]

const NEVER = [
  'Asks for a secret key or recovery phrase',
  'Moves funds without a signature from the right wallet',
  'Shows a bounty as funded before the network confirms it',
  'Publishes invented numbers, reviews or partner logos',
]

function short(value: string) {
  return `${value.slice(0, 6)}…${value.slice(-6)}`
}

/** One cell of the facts grid: a label above its value. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 bg-card px-4 py-4 sm:px-5 sm:py-5">
      <dt className="text-[0.8125rem] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-[1.0625rem] font-medium">{children}</dd>
    </div>
  )
}

/**
 * Live facts about this deployment: the network, the contract and what has happened on it so far. The window
 * sits whole inside its backdrop, so no row is ever cut off.
 */
function AtAGlance() {
  const { data: config, isPending: configPending } = usePublicConfig()
  const { data: stats, isPending: statsPending } = usePublicStats()
  const contractHref = config?.contract_id
    ? (config.contract_explorer_url ?? contractExplorerUrl(config, config.contract_id))
    : null
  /** While a query is in flight a bar stands in for the value, so nothing reads as an empty deployment. */
  const pending = (loading: boolean, width: string, value: ReactNode) =>
    loading ? <Skeleton className={`h-5 ${width}`} /> : value

  return (
    <AppWindow
      title={
        <h3 id="glance-window" className="text-[0.8125rem] font-medium">
          At a glance
        </h3>
      }
    >
      <dl className="grid grid-cols-1 gap-px bg-border min-[420px]:grid-cols-2 lg:grid-cols-3">
        <Fact label="Network">
          {pending(
            configPending,
            'w-28',
            config ? `Stellar ${networkDisplayName(config.network, config.blockchain_mode)}` : '—',
          )}
        </Fact>
        <Fact label="Escrow contract">
          {pending(
            configPending,
            'w-32',
            config?.contract_id ? (
              contractHref ? (
                <a
                  href={contractHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Escrow contract ${config.contract_id} on the Stellar explorer`}
                  className="inline-flex items-center gap-1.5 font-mono text-[0.875rem] font-normal hover:underline"
                >
                  {short(config.contract_id)} <ExternalLink className="size-3.5" aria-hidden />
                </a>
              ) : (
                <span className="font-mono text-[0.875rem] font-normal">{short(config.contract_id)}</span>
              )
            ) : (
              '—'
            ),
          )}
        </Fact>
        <Fact label="Dispute arbiter">
          {pending(
            configPending,
            'w-32',
            config?.arbiter_address ? (
              <span className="font-mono text-[0.875rem] font-normal">{short(config.arbiter_address)}</span>
            ) : (
              '—'
            ),
          )}
        </Fact>
        <Fact label="Bounties published">
          {pending(
            statsPending,
            'w-12',
            <span className="amount">{stats ? formatNumber(stats.published_bounties) : '—'}</span>,
          )}
        </Fact>
        <Fact label="Members">
          {pending(
            statsPending,
            'w-12',
            <span className="amount">{stats ? formatNumber(stats.registered_users) : '—'}</span>,
          )}
        </Fact>
        <Fact label="Verified payouts">
          {pending(
            statsPending,
            'w-20',
            stats ? (
              <>
                <span className="amount">
                  {formatAmount(stats.verified_payout_volume, { maxDecimals: 2 })}
                </span>{' '}
                <span className="text-sm font-normal text-muted-foreground">XLM</span>
              </>
            ) : (
              '—'
            ),
          )}
        </Fact>
      </dl>
    </AppWindow>
  )
}

function List({
  id,
  title,
  items,
  tone,
}: {
  id: string
  title: string
  items: string[]
  tone: 'yes' | 'no'
}) {
  const Icon = tone === 'yes' ? Check : X
  const mark = tone === 'yes' ? 'text-success' : 'text-destructive'
  return (
    <div className="bg-card">
      <h3
        id={id}
        className="flex items-center gap-2.5 border-b px-6 py-5 text-[1.0625rem] font-medium sm:px-8"
      >
        <Icon className={`size-4 shrink-0 ${mark}`} aria-hidden />
        {title}
      </h3>
      <ul aria-labelledby={id} className="divide-y px-6 sm:px-8">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-3 py-4 text-[0.9375rem] leading-relaxed">
            <Icon className={`mt-1 size-4 shrink-0 ${mark}`} aria-hidden />
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function AboutPage() {
  const small = useMediaQuery('(max-width: 767px)')
  return (
    <>
      {/* The headline sits beside the argument for the product, so the first screen reads as one thought
          rather than a title next to an unrelated panel. */}
      <section aria-labelledby="about-title" className="relative isolate overflow-clip">
        {/* A wash of the brand colour rising behind the headline. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-128 bg-[radial-gradient(58%_62%_at_16%_0%,color-mix(in_oklab,var(--primary)_10%,transparent),transparent)]"
        />
        {/* The same live network as the landing hero and the sign-in screens, weighted to the headline side.
            It loads only where WebGL runs and stands still under reduced motion. */}
        <Scene
          name="constellation"
          density={small ? 80 : 150}
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-128 animate-in duration-1000 fade-in-0 sm:h-152"
          style={HERO_SCENE_MASK}
        />
        <PageContainer className="pt-12 pb-10 sm:pt-20 sm:pb-14">
          <PageBreadcrumbs items={[{ label: 'Home', to: '/' }, { label: 'About' }]} className="mb-6" />
          <div className="grid gap-x-16 gap-y-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:items-end">
            <div>
              <MonoLabel>About</MonoLabel>
              <h1
                id="about-title"
                className="mt-4 max-w-[13ch] font-display text-[2.5rem] leading-[0.98] tracking-[-0.03em] text-balance sm:text-[3.5rem] xl:text-[4.5rem]"
              >
                Why BountyFlow exists
              </h1>
            </div>
            <div className="lg:pb-2">
              <p className="text-lg leading-[1.6] sm:text-xl">
                Paid open work, like bug fixes, audits, docs and design, usually runs on trust. A requester
                promises a reward and the contributor hopes it arrives. When it doesn’t, there’s little
                recourse.
              </p>
              <p className="mt-4 text-base leading-7 text-muted-foreground">
                BountyFlow moves that promise into a Soroban smart contract on Stellar. Low fees and fast
                finality make it practical to escrow even small rewards and pay them out as soon as work is
                approved.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button asChild variant="inverse" size="pill">
                  <Link to="/how-it-works">See how it works</Link>
                </Button>
                {/* The argument above is abstract; this is the thing itself. The source link keeps its
                    place in the footer. */}
                <Button asChild variant="outline" size="pill">
                  <Link to="/bounties">
                    <Search /> Browse bounties
                  </Link>
                </Button>
              </div>
            </div>
          </div>
        </PageContainer>
      </section>

      {/* The tinted band carries its own copy, so it reads as a section rather than a decorated gap. */}
      <section aria-labelledby="deployment-title" className="pb-16 sm:pb-24">
        <PageContainer>
          <Atmosphere tone="dawn" className="p-5 sm:p-8 lg:p-12">
            <div className="grid gap-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.5fr)] lg:items-center lg:gap-14">
              <div className="max-w-md">
                <MonoLabel>This deployment</MonoLabel>
                <h2
                  id="deployment-title"
                  className="mt-3 font-display text-[1.75rem] leading-[1.08] sm:text-[2.125rem]"
                >
                  Running on Stellar Testnet
                </h2>
                <p className="mt-4 text-[0.9375rem] leading-relaxed text-muted-foreground sm:text-base">
                  Every escrow, payout and refund is a real contract call you can inspect on the explorer,
                  using test XLM that has no monetary value.
                </p>
              </div>
              <AtAGlance />
            </div>
          </Atmosphere>
        </PageContainer>
      </section>

      <section aria-labelledby="principles-title" className="pb-16 sm:pb-24">
        <PageContainer>
          <SectionHeading id="principles-title" label="Principles" title="What it holds itself to" />
          <ul className="mt-10 grid gap-px overflow-hidden rounded-2xl border bg-border sm:mt-12 md:grid-cols-3">
            {PRINCIPLES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex flex-col bg-card p-6 sm:p-8 md:min-h-60">
                <span
                  aria-hidden
                  className="flex size-10 items-center justify-center rounded-full bg-primary/8 text-primary-emphasis"
                >
                  <Icon className="size-5" />
                </span>
                <h3 className="mt-8 text-[1.0625rem] font-medium md:mt-auto md:pt-12">{title}</h3>
                <p className="mt-2 text-[0.9375rem] leading-relaxed text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
        </PageContainer>
      </section>

      <section aria-labelledby="scope-title" className="pb-20 sm:pb-28">
        <PageContainer>
          <SectionHeading id="scope-title" label="Scope" title="What BountyFlow does, and never does" />
          <div className="mt-10 grid gap-px overflow-hidden rounded-2xl border bg-border sm:mt-12 lg:grid-cols-2">
            <List id="does-title" title="BountyFlow does" items={DOES} tone="yes" />
            <List id="never-title" title="BountyFlow never" items={NEVER} tone="no" />
          </div>
        </PageContainer>
      </section>

      <CallToAction />
    </>
  )
}
