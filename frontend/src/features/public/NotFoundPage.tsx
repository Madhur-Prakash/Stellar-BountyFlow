import { ArrowLeft, Search } from 'lucide-react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'

export default function NotFoundPage() {
  return (
    <PageContainer size="narrow" className="flex flex-col items-center py-20 text-center sm:py-28">
      <span className="rounded-[4px] border bg-card px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
        404
      </span>
      <h1 className="font-display mt-4 text-[1.625rem] leading-tight">Page not found</h1>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        This page doesn’t exist or has been moved.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button asChild>
          <Link to="/">
            <ArrowLeft aria-hidden /> Back to home
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/bounties">
            <Search aria-hidden /> Explore bounties
          </Link>
        </Button>
      </div>
    </PageContainer>
  )
}
