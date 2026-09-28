import { ArrowLeft, Search } from 'lucide-react'
import { Link } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'

export default function NotFoundPage() {
  return (
    <PageContainer size="narrow" className="py-24 text-center sm:py-32">
      <p className="font-mono text-sm text-muted-foreground tabular-nums">404</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Page not found</h1>
      <p className="mx-auto mt-3 max-w-md text-muted-foreground">
        The page you were looking for doesn’t exist or has moved. If you followed a bounty link, it may have
        been unpublished by its requester.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link to="/">
            <ArrowLeft /> Back to home
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/bounties">
            <Search /> Explore bounties
          </Link>
        </Button>
      </div>
    </PageContainer>
  )
}
