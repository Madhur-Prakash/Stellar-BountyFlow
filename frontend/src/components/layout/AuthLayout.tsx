import { ArrowLeft } from 'lucide-react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router'

import { Logo } from '@/components/brand/Logo'
import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { Scene } from '@/components/three/Scene'
import { Button } from '@/components/ui/button'

import { AnimatedOutlet } from './AnimatedOutlet'

/**
 * Keeps the network clear of the middle of the screen, where the heading and the card sit, so it reads as a
 * quiet edge to the page rather than something competing with the form.
 */
const SCENE_MASK: CSSProperties = {
  maskImage: 'radial-gradient(64% 58% at 50% 46%, transparent 26%, black 82%)',
}

/**
 * Sign in, register and the password / email screens: a slim top row and one centred column on the canvas
 * holding the screen's heading and its card (AuthCard). The same network as the landing hero drifts behind
 * it, faded away from the middle; it loads lazily and stands still under reduced motion.
 */
export function AuthLayout() {
  return (
    <div className="relative isolate flex min-h-dvh flex-col bg-background">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(70%_50%_at_50%_0%,color-mix(in_oklab,var(--primary)_7%,transparent),transparent)]"
      />
      <Scene
        name="constellation"
        density={110}
        className="pointer-events-none absolute inset-0 -z-10 animate-in opacity-70 duration-1000 fade-in-0 dark:opacity-90"
        style={SCENE_MASK}
      />
      <SkipLink />
      <header className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6">
        <Link to="/" aria-label="BountyFlow home" className="inline-flex rounded-md">
          <Logo />
        </Link>
        <div className="flex items-center gap-1">
          <Button asChild variant="ghost" size="sm" className="rounded-full text-muted-foreground">
            <Link to="/">
              <ArrowLeft aria-hidden /> Back to site
            </Link>
          </Button>
          <ThemeToggle className="rounded-full" />
        </div>
      </header>
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="flex flex-1 items-center justify-center px-4 pt-6 pb-16 outline-none sm:px-6 sm:pt-4 sm:pb-20"
      >
        <AnimatedOutlet className="w-full max-w-160" />
      </main>
    </div>
  )
}
