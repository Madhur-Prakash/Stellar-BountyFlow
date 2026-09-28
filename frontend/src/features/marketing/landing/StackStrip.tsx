import { FileCode2, Orbit, Radio, Server, Telescope, Wallet, type LucideIcon } from 'lucide-react'

import { PageContainer } from '@/components/layout/PageContainer'
import { Scene } from '@/components/three/Scene'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { usePublicConfig } from '@/lib/api/queries/config'
import { networkDisplayName } from '@/lib/stellar/explorer'

import { SECTION_TITLE } from './SectionHeading'

type Piece = { icon: LucideIcon; name: string; role: string }

/** The explorer this deployment links to, named after its host. */
function explorerName(base: string | undefined): string {
  if (!base) return 'Stellar Expert'
  try {
    const host = new URL(base).hostname.replace(/^www\./, '')
    return host === 'stellar.expert' ? 'Stellar Expert' : host
  } catch {
    return 'Stellar Expert'
  }
}

/**
 * The real stack underneath BountyFlow, named plainly: the network, the escrow contract platform, the wallet,
 * the explorer every transaction links to, and the two network services the API talks to. The dotted globe
 * rising behind it is the network. Decorative, large screens only.
 */
export function StackStrip() {
  const wide = useMediaQuery('(min-width: 1024px)')
  const { data } = usePublicConfig()
  const network = data ? networkDisplayName(data.network, data.blockchain_mode) : 'network'
  const pieces: Piece[] = [
    { icon: Orbit, name: 'Stellar', role: network },
    { icon: FileCode2, name: 'Soroban', role: 'Escrow contract' },
    { icon: Wallet, name: 'Freighter', role: 'Wallet signing' },
    { icon: Telescope, name: explorerName(data?.explorer_base_url), role: 'Public explorer' },
    { icon: Server, name: 'Horizon', role: 'Network API' },
    { icon: Radio, name: 'Soroban RPC', role: 'Contract calls' },
  ]

  return (
    <section
      aria-labelledby="stack-title"
      className="relative isolate overflow-hidden pt-20 pb-20 sm:pt-28 lg:pb-96"
    >
      {wide && (
        <Scene
          name="globe"
          density={9000}
          dotSize={5.5}
          markerScale={0.6}
          className="pointer-events-none absolute top-60 left-1/2 -z-10 size-[72rem] -translate-x-1/2 animate-in mask-[linear-gradient(to_bottom,black_14%,transparent_33%)] duration-1000 fade-in-0"
        />
      )}
      <PageContainer className="text-center">
        <h2 id="stack-title" className={SECTION_TITLE}>
          Built on the Stellar stack
        </h2>
        <ul className="mx-auto mt-12 grid max-w-6xl grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-3 lg:flex lg:flex-wrap lg:justify-center lg:gap-x-10">
          {pieces.map(({ icon: Icon, name, role }) => (
            <li key={name} className="flex items-center gap-3 text-left">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border bg-card text-foreground shadow-soft">
                <Icon className="size-4.5" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[0.9375rem] font-medium">{name}</span>
                <span className="block truncate font-mono text-xs text-muted-foreground">{role}</span>
              </span>
            </li>
          ))}
        </ul>
      </PageContainer>
    </section>
  )
}
