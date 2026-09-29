import { Link } from 'react-router'

import { GithubMark } from '@/components/brand/GithubMark'
import { Logo } from '@/components/brand/Logo'
import { usePublicConfig } from '@/lib/api/queries/config'
import { COPYRIGHT_YEAR, SITE } from '@/lib/site'
import { networkDisplayName } from '@/lib/stellar/explorer'

const COLUMNS: { title: string; links: { label: string; to: string; external?: boolean }[] }[] = [
  {
    title: 'Product',
    links: [
      { label: 'Marketplace', to: '/bounties' },
      { label: 'Post a bounty', to: '/app/bounties/create' },
      { label: 'How it works', to: '/how-it-works' },
      { label: 'Escrow contract', to: '/#escrow' },
      { label: 'About', to: '/about' },
    ],
  },
  {
    title: 'Guide',
    links: [
      { label: 'Getting started', to: '/guide#getting-started' },
      { label: 'Wallets & Freighter', to: '/guide#wallets' },
      { label: 'Funding & escrow', to: '/guide#escrow' },
      { label: 'Disputes', to: '/guide#disputes' },
    ],
  },
  {
    title: 'Stellar',
    links: [
      { label: 'Stellar network', to: SITE.stellarUrl, external: true },
      { label: 'Soroban smart contracts', to: SITE.sorobanDocsUrl, external: true },
      { label: 'Freighter wallet', to: SITE.freighterUrl, external: true },
    ],
  },
  {
    title: 'Legal',
    links: [
      { label: 'Terms', to: '/terms' },
      { label: 'Privacy', to: '/privacy' },
    ],
  },
]

/** The network this deployment runs on, from the API's public config. */
function FooterNetwork() {
  const { data } = usePublicConfig()
  if (!data) return null
  return <p>Running on Stellar {networkDisplayName(data.network, data.blockchain_mode)}</p>
}

export function MarketingFooter() {
  return (
    <footer className="border-t bg-surface">
      <div className="mx-auto max-w-384 px-4 py-14 sm:px-6 lg:px-8 2xl:px-12">
        <div className="grid gap-12 lg:grid-cols-[1.2fr_2fr]">
          <div className="space-y-6">
            <Logo />
            {/* The tagline as a large halftone wordmark: dots of ink that read as type from a distance. The
                dots overlap their 3.4px cell, so the letters read as near-solid ink and the grain only shows
                close up. */}
            <p className="sr-only">{SITE.tagline}</p>
            <div
              aria-hidden
              className="bg-[radial-gradient(circle,currentColor_2.15px,transparent_2.4px)] bg-size-[3.4px_3.4px] bg-clip-text font-display text-[clamp(2.25rem,4.2vw,4rem)] leading-[0.94] font-extrabold tracking-[-0.035em] text-foreground select-none dark:text-foreground/80"
              style={{ WebkitTextFillColor: 'transparent' }}
            >
              <span className="block whitespace-nowrap">Work gets done.</span>
              <span className="block whitespace-nowrap">Rewards move</span>
              <span className="block whitespace-nowrap">transparently.</span>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {SITE.githubUrl && (
                <a
                  href={SITE.githubUrl}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="inline-flex h-9 items-center gap-2 rounded-md px-2 text-sm text-muted-foreground hover:text-foreground"
                >
                  <GithubMark /> Source on GitHub
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            {COLUMNS.map((col) => (
              <nav key={col.title} aria-label={col.title}>
                <h2 className="text-sm font-medium">{col.title}</h2>
                <ul className="mt-3 space-y-1">
                  {col.links.map((l) => (
                    <li key={l.label}>
                      {l.external ? (
                        <a
                          href={l.to}
                          target="_blank"
                          rel="noopener noreferrer nofollow"
                          className="inline-flex min-h-9 items-center text-sm text-muted-foreground hover:text-foreground"
                        >
                          {l.label}
                        </a>
                      ) : (
                        <Link
                          to={l.to}
                          className="inline-flex min-h-9 items-center text-sm text-muted-foreground hover:text-foreground"
                        >
                          {l.label}
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
        </div>
        <div className="mt-10 flex flex-col gap-2 border-t pt-6 text-xs text-muted-foreground sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <p>
              BountyFlow is an independent project built on Stellar and Soroban. It is not affiliated with the
              Stellar Development Foundation.
            </p>
            {/* Built and maintained by one person; the year is fixed to the release rather than "now", so a
                stale clock on a viewer's machine cannot change what the notice claims. */}
            <p>
              © {COPYRIGHT_YEAR} {SITE.name}. All rights reserved.
            </p>
          </div>
          <FooterNetwork />
        </div>
      </div>
    </footer>
  )
}
