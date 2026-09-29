import { Check, ExternalLink, KeyRound, Scale, ShieldCheck, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { GithubMark } from '@/components/brand/GithubMark'
import { PageBreadcrumbs } from '@/components/layout/PageBreadcrumbs'
import { PageContainer } from '@/components/layout/PageContainer'
import { AppWindow, Atmosphere, MonoLabel } from '@/components/marketing'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { usePublicStats } from '@/lib/api/queries/analytics'
import { usePublicConfig } from '@/lib/api/queries/config'
import { formatNumber } from '@/lib/format'
import { formatAmount } from '@/lib/money'
import { SITE } from '@/lib/site'
import { contractExplorerUrl, networkDisplayName } from '@/lib/stellar/explorer'

import { CallToAction } from './landing/CallToAction'

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

/** Live facts about this deployment: the network, the contract and what has happened on it so far. */
function AtAGlance() {
  const { data: config } = usePublicConfig()
  const { data: stats, isPending } = usePublicStats()
  const contractHref = config?.contract_id
    ? (config.contract_explorer_url ?? contractExplorerUrl(config, config.contract_id))
    : null
  const figure = (value: ReactNode) => (isPending ? <Skeleton className="h-6 w-16" /> : value)

  return (
    <aside aria-labelledby="glance-title">
      <AppWindow
        className="rounded-b-none border-b-0"
        title={
          <h2 id="glance-title" className="text-[0.8125rem] font-medium">
            At a glance
          </h2>
        }
      >
        <dl className="grid grid-cols-1 gap-px bg-border min-[420px]:grid-cols-2">
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
                  className="inline-flex items-center gap-1.5 font-mono text-[0.875rem] font-normal hover:underline"
                >
                  {short(config.contract_id)} <ExternalLink className="size-3.5" aria-hidden />
                </a>
              ) : (
                <span className="font-mono text-[0.875rem] font-normal">{short(config.contract_id)}</span>
              )
            ) : (
              '—'
            )}
          </Fact>
          <Fact label="Dispute arbiter">
            {config?.arbiter_address ? (
              <span className="font-mono text-[0.875rem] font-normal">{short(config.arbiter_address)}</span>
            ) : (
              '—'
            )}
          </Fact>
          <Fact label="Bounties published">
            {figure(<span className="amount">{stats ? formatNumber(stats.published_bounties) : '—'}</span>)}
          </Fact>
          <Fact label="Members">
            {figure(<span className="amount">{stats ? formatNumber(stats.registered_users) : '—'}</span>)}
          </Fact>
          <Fact label="Verified payouts">
            {figure(
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
    </aside>
  )
}

/** A mono label and a section heading, as on the landing page. */
function Heading({ id, label, title }: { id: string; label: string; title: string }) {
  return (
    <div className="max-w-3xl">
      <MonoLabel>{label}</MonoLabel>
      <h2 id={id} className="mt-3 font-display text-[2rem] leading-[1.1] sm:text-[2.5rem]">
        {title}
      </h2>
    </div>
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
  return (
    <div className="bg-card">
      <h3 id={id} className="border-b px-6 py-5 text-[1.0625rem] font-medium sm:px-8">
        {title}
      </h3>
      <ul aria-labelledby={id} className="divide-y px-6 sm:px-8">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-3 py-4 text-[0.9375rem] leading-relaxed">
            <Icon
              className={
                tone === 'yes' ? 'mt-1 size-4 shrink-0 text-success' : 'mt-1 size-4 shrink-0 text-destructive'
              }
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
      <section aria-labelledby="about-title">
        <PageContainer className="grid gap-12 pt-14 pb-16 sm:pt-24 sm:pb-24 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-center lg:gap-16">
          <div className="max-w-2xl">
            <PageBreadcrumbs items={[{ label: 'Home', to: '/' }, { label: 'About' }]} className="mb-5" />
            <MonoLabel>About</MonoLabel>
            <h1
              id="about-title"
              className="mt-4 font-display text-[2.5rem] leading-[1] tracking-[-0.03em] sm:text-[3.5rem] xl:text-[4.25rem]"
            >
              Why we built BountyFlow
            </h1>
            <p className="mt-6 text-lg leading-[1.6] text-muted-foreground sm:text-xl">
              Paid open work, like bug fixes, audits, docs and design, usually runs on trust. A requester
              promises a reward and the contributor hopes it arrives. When it doesn’t, there’s little
              recourse.
            </p>
            <div className="mt-5 space-y-4 text-base leading-7 text-muted-foreground">
              <p>
                BountyFlow moves that promise into a Soroban smart contract on Stellar. Low fees and fast
                finality make it practical to escrow even small rewards and pay them out as soon as work is
                approved.
              </p>
              <p>
                This deployment runs on Stellar Testnet. Every escrow, payout and refund is a real contract
                call you can inspect on the explorer, using test XLM that has no monetary value.
              </p>
            </div>
            <div className="mt-9 flex flex-wrap gap-3">
              <Button asChild variant="inverse" size="pill">
                <Link to="/how-it-works">See how it works</Link>
              </Button>
              {SITE.githubUrl && (
                <Button asChild variant="outline" size="pill">
                  <a href={SITE.githubUrl} target="_blank" rel="noopener noreferrer nofollow">
                    <GithubMark /> View the source
                  </a>
                </Button>
              )}
            </div>
          </div>

          <Atmosphere
            tone="dusk"
            className="px-4 pt-10 sm:px-12 sm:pt-14 lg:px-14 lg:pt-20 xl:px-16 xl:pt-24"
          >
            <AtAGlance />
          </Atmosphere>
        </PageContainer>
      </section>

      <section aria-labelledby="principles-title" className="py-16 sm:py-24">
        <PageContainer>
          <Heading id="principles-title" label="Principles" title="What we hold ourselves to" />
          <ul className="mt-10 grid gap-px border bg-border sm:mt-12 md:grid-cols-3">
            {PRINCIPLES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex flex-col bg-card p-6 sm:p-8 md:min-h-60">
                <Icon className="size-5 text-primary-emphasis" aria-hidden />
                <h3 className="mt-8 text-[1.0625rem] font-medium md:mt-auto md:pt-12">{title}</h3>
                <p className="mt-2 text-[0.9375rem] leading-relaxed text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
        </PageContainer>
      </section>

      <section aria-labelledby="scope-title" className="pb-20 sm:pb-28">
        <PageContainer>
          <Heading id="scope-title" label="Scope" title="What BountyFlow does, and never does" />
          <div className="mt-10 grid gap-px border bg-border sm:mt-12 lg:grid-cols-2">
            <List id="does-title" title="BountyFlow does" items={DOES} tone="yes" />
            <List id="never-title" title="BountyFlow never" items={NEVER} tone="no" />
          </div>
        </PageContainer>
      </section>

      <CallToAction />
    </>
  )
}
