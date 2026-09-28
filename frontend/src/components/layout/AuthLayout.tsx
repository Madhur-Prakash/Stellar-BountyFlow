import { ArrowLeft, CircleDollarSign, FileCheck2, ShieldCheck } from 'lucide-react'
import { useRef } from 'react'
import { Link } from 'react-router'

import { Logo } from '@/components/brand/Logo'
import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { SplitHeading } from '@/components/motion/SplitHeading'
import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap, useGSAP } from '@/lib/gsap'

import { AnimatedOutlet } from './AnimatedOutlet'
import { BountyStack } from './BountyStack'

const POINTS = [
  { icon: ShieldCheck, title: 'Escrow before work starts' },
  { icon: FileCheck2, title: 'Clear acceptance criteria' },
  { icon: CircleDollarSign, title: 'Payouts you can verify on-chain' },
]

export function AuthLayout() {
  const aside = useRef<HTMLElement>(null)
  useGSAP(
    () => {
      if (!motionAllowed()) return
      gsap.from('[data-auth-fade]', { autoAlpha: 0, y: 12, duration: 0.6, stagger: 0.08, delay: 0.7 })
    },
    { scope: aside },
  )

  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1.1fr)_minmax(0,34rem)]">
      <SkipLink />
      <aside
        ref={aside}
        className="relative isolate hidden overflow-hidden border-r border-vault-line bg-vault text-vault-foreground lg:flex lg:flex-col"
        aria-label="About BountyFlow"
      >
        {/* The same ledger grid as the escrow section, fading out towards the edges. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 bg-[linear-gradient(var(--vault-line)_1px,transparent_1px),linear-gradient(90deg,var(--vault-line)_1px,transparent_1px)] mask-[radial-gradient(ellipse_80%_70%_at_60%_45%,black,transparent)] bg-size-[56px_56px] opacity-60"
        />
        <div className="flex h-full flex-col px-12 py-10 xl:px-16">
          <Link to="/" aria-label="BountyFlow home" className="w-fit rounded-md">
            <Logo />
          </Link>

          <div className="my-auto grid gap-14 py-12 xl:grid-cols-[minmax(0,1fr)_minmax(0,19rem)] xl:items-center">
            <div className="max-w-md">
              <SplitHeading
                trigger="load"
                expand
                className="font-display text-[clamp(2.75rem,3.6vw,3.75rem)] leading-[0.98] tracking-tight"
              >
                Work gets done. Rewards move transparently.
              </SplitHeading>
              <p data-auth-fade className="mt-6 text-[1.0625rem] leading-relaxed text-vault-muted">
                Sign in to post work and fund it from your own wallet, or to apply for bounties and get paid
                straight from escrow.
              </p>
            </div>
            <div>
              <BountyStack />
              <p className="mt-2 text-sm text-vault-muted">Open on BountyFlow right now.</p>
            </div>
          </div>

          <ul className="grid gap-3 border-t border-vault-line pt-6 xl:grid-cols-3">
            {POINTS.map(({ icon: Icon, title }) => (
              <li key={title} data-auth-fade className="flex items-center gap-2.5 text-sm font-medium">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-vault-line bg-vault-panel">
                  <Icon className="size-4 text-vault-accent" aria-hidden />
                </span>
                {title}
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <div className="flex min-h-dvh flex-col">
        <div className="flex h-16 items-center justify-between px-4 sm:px-8">
          <Link
            to="/"
            className="inline-flex min-h-10 items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden />{' '}
            <span className="lg:hidden">
              <Logo />
            </span>
            <span className="hidden lg:inline">Back to site</span>
          </Link>
          <ThemeToggle />
        </div>
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="flex flex-1 items-start justify-center px-4 pt-6 pb-16 outline-none sm:px-8 sm:pt-12 lg:items-center lg:pt-0"
        >
          <div className="w-full max-w-md">
            <AnimatedOutlet />
          </div>
        </main>
      </div>
    </div>
  )
}
