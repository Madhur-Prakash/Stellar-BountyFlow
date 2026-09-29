import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router'

import { Logo } from '@/components/brand/Logo'
import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { Button } from '@/components/ui/button'

import { AnimatedOutlet } from './AnimatedOutlet'

/**
 * Sign in, register and the password / email screens: a slim top row and one centred column on the canvas
 * holding the screen's heading and its card (AuthCard).
 */
export function AuthLayout() {
  return (
    <div className="relative isolate flex min-h-dvh flex-col bg-background">
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
