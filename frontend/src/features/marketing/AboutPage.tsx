import { Check, ExternalLink, KeyRound, Scale, ShieldCheck, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { GithubMark } from '@/components/brand/GithubMark'
import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { usePublicStats } from '@/lib/api/queries/analytics'
import { usePublicConfig } from '@/lib/api/queries/config'
import { formatNumber } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { SITE } from '@/lib/site'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'

import { CallToAction } from './landing/CallToAction'
import { SECTION, SectionHeading } from './landing/SectionHeading'

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

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-right text-sm font-medium">{children}</dd>
    </div>
  )
}

/** Live facts about this deployment: the network, the contract and what has happened on it so far. */
function AtAGlance() {
  const { data: config } = usePublicConfig()
  const { data: stats, isPending } = usePublicStats()
  const contractHref = config?.contract_id
    ? (config.contract_explorer_url ?? contractExplorerUrl(config, config.contract_id))
    : null
  const figure = (value: ReactNode) => (isPending ? <Skeleton className="ml-auto h-4 w-14" /> : value)

  return (
    <aside aria-labelledby="glance-title" className="rounded-xl border bg-card shadow-soft">
      <h2 id="glance-title" className="border-b px-5 py-4 text-[0.9375rem] font-semibold">
        At a glance
      </h2>
      <dl className="divide-y px-5">
        <Fact label="Network">
          {config ? `Stellar ${networkDisplayName(config.network, config.blockchain_mode)}` : '—'}
        </Fact>
        <Fact label="Escrow contract">
          {config?.contract_id ? (
            contractHref ? (
              <a
                href={contractHref}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Escrow contract ${config.contract_id} on the Stellar explorer`}
                className="inline-flex items-center gap-1 font-mono text-[0.8125rem] hover:underline"
              >
                {short(config.contract_id)} <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : (
              <span className="font-mono text-[0.8125rem]">{short(config.contract_id)}</span>
            )
          ) : (
            '—'
          )}
        </Fact>
        <Fact label="Dispute arbiter">
          {config?.arbiter_address ? (
            <span className="font-mono text-[0.8125rem]">{short(config.arbiter_address)}</span>
          ) : (
            '—'
          )}
        </Fact>
        <Fact label="Bounties published">
          {figure(stats ? formatNumber(stats.published_bounties) : '—')}
        </Fact>
        <Fact label="Members">{figure(stats ? formatNumber(stats.registered_users) : '—')}</Fact>
        <Fact label="Verified payouts">
          {figure(stats ? `${formatAmount(stats.verified_payout_volume, { maxDecimals: 2 })} XLM` : '—')}
        </Fact>
      </dl>
    </aside>
  )
}

function List({ id, title, items, tone }: { id: string; title: string; items: string[]; tone: 'yes' | 'no' }) {
  const Icon = tone === 'yes' ? Check : X
  return (
    <div className="rounded-xl border bg-card shadow-soft">
      <h3 id={id} className="border-b px-5 py-4 text-[0.9375rem] font-semibold">
        {title}
      </h3>
      <ul aria-labelledby={id} className="divide-y px-5">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-3 py-3.5 text-sm">
            <Icon
              className={tone === 'yes' ? 'mt-0.5 size-4 shrink-0 text-success' : 'mt-0.5 size-4 shrink-0 text-destructive'}
              aria-hidden
            />
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function AboutPage() {
  return (
    <>
      <section className="relative isolate overflow-hidden border-b">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-80 bg-[radial-gradient(60%_70%_at_30%_0%,color-mix(in_oklab,var(--primary)_8%,transparent),transparent)]"
        />
        <PageContainer className="grid gap-10 py-14 sm:py-20 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:gap-16">
          <div className="max-w-2xl">
            <h1 className="font-display text-[2.125rem] leading-[1.1] sm:text-[2.625rem]">
              Why we built BountyFlow
            </h1>
            <div className="mt-6 space-y-4 text-[1.0625rem] leading-relaxed text-muted-foreground">
              <p>
                Paid open work, like bug fixes, audits, docs and design, usually runs on trust. A requester
                promises a reward and the contributor hopes it arrives. When it doesn’t, there’s little recourse.
              </p>
              <p>
                BountyFlow moves that promise into a Soroban smart contract on Stellar. Low fees and fast
                finality make it practical to escrow even small rewards and pay them out as soon as work is
                approved.
              </p>
              <p>
                This deployment runs on Stellar Testnet. Every escrow, payout and refund is a real contract call
                you can inspect on the explorer, using test XLM that has no monetary value.
              </p>
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild>
                <Link to="/how-it-works">See how it works</Link>
              </Button>
              {SITE.githubUrl && (
                <Button asChild variant="outline">
                  <a href={SITE.githubUrl} target="_blank" rel="noopener noreferrer nofollow">
                    <GithubMark /> View the source
                  </a>
                </Button>
              )}
            </div>
          </div>
          <div className="lg:pt-2">
            <AtAGlance />
          </div>
        </PageContainer>
      </section>

      <section aria-labelledby="principles-title" className={SECTION}>
        <PageContainer>
          <SectionHeading id="principles-title" title="What we hold ourselves to" />
          <ul className="mt-8 grid gap-6 md:grid-cols-3">
            {PRINCIPLES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="rounded-xl border bg-card p-6 shadow-soft">
                <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-4" aria-hidden />
                </span>
                <h3 className="mt-4 text-[0.9375rem] font-semibold">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
        </PageContainer>
      </section>

      <section aria-labelledby="scope-title" className="pb-16 sm:pb-20">
        <PageContainer>
          <SectionHeading id="scope-title" title="What BountyFlow does, and never does" />
          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            <List id="does-title" title="BountyFlow does" items={DOES} tone="yes" />
            <List id="never-title" title="BountyFlow never" items={NEVER} tone="no" />
          </div>
        </PageContainer>
      </section>

      <CallToAction />
    </>
  )
}
