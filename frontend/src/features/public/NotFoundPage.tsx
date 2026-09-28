import { ArrowLeft, Search } from 'lucide-react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Atmosphere } from '@/components/marketing'
import { Button } from '@/components/ui/button'

export default function NotFoundPage() {
  return (
    <PageContainer className="py-8 sm:py-12">
      <Atmosphere
        tone="dune"
        className="flex min-h-[30rem] flex-col items-center justify-center px-6 py-16 text-center sm:min-h-[36rem] sm:py-20"
      >
        <p
          aria-hidden
          className="font-display text-[7.5rem] leading-[0.9] tracking-[-0.05em] sm:text-[11rem] lg:text-[13.5rem]"
        >
          404
        </p>
        <h1 className="mt-6 font-display text-[1.75rem] leading-tight sm:text-[2.25rem]">
          Page not found
        </h1>
        <p className="mt-3 max-w-sm text-base text-foreground/80 sm:text-lg">
          This page doesn’t exist or has been moved.
        </p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <Button asChild variant="inverse" size="pill">
            <Link to="/">
              <ArrowLeft aria-hidden /> Back to home
            </Link>
          </Button>
          <Button asChild variant="outline" size="pill" className="dark:bg-background/40">
            <Link to="/bounties">
              <Search aria-hidden /> Explore bounties
            </Link>
          </Button>
        </div>
      </Atmosphere>
    </PageContainer>
  )
}
