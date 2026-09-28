import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router'

import { Logo } from '@/components/brand/Logo'
import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { Button } from '@/components/ui/button'

import { AnimatedOutlet } from './AnimatedOutlet'

/** Sign in, register and the password / email screens: a slim top row and one centred column on the canvas. */
export function AuthLayout() {
  return (
    <div className="relative isolate flex min-h-dvh flex-col bg-background">
      <SkipLink />
      {/* A faint wash of the accent from the top edge, in either theme. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[36rem] bg-[radial-gradient(60rem_32rem_at_50%_-12rem,color-mix(in_oklch,var(--primary)_14%,transparent),transparent_70%)] dark:bg-[radial-gradient(60rem_32rem_at_50%_-12rem,color-mix(in_oklch,var(--primary)_18%,transparent),transparent_70%)]"
      />
      <header className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6">
        <Link to="/" aria-label="BountyFlow home" className="inline-flex rounded-md">
          <Logo />
        </Link>
        <div className="flex items-center gap-1">
          <Button asChild variant="ghost" size="sm" className="text-muted-foreground">
            <Link to="/">
              <ArrowLeft aria-hidden /> Back to site
            </Link>
          </Button>
          <ThemeToggle />
        </div>
      </header>
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="flex flex-1 items-center justify-center px-4 pt-6 pb-20 outline-none sm:px-6 sm:pt-2"
      >
        <AnimatedOutlet className="w-full max-w-[26rem]" />
      </main>
    </div>
  )
}
