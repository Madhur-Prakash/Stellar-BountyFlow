import { Bookmark, Search } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyGridSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useSavedBounties } from '@/lib/api/queries/bounties'
import { useSavedSearches } from '@/lib/api/queries/discovery'
import { formatNumber } from '@/lib/format'

import { SavedSearchesPanel } from './SavedSearchesPanel'

type Tab = 'bounties' | 'searches'

function SavedBounties() {
  const [page, setPage] = useState(1)
  const query = useSavedBounties({ page, page_size: 12 })
  return (
    <QueryView
      query={query}
      skeleton="app-saved"
      loading={<BountyGridSkeleton count={3} />}
      isEmpty={(d) => d.items.length === 0}
      empty={{
        icon: Bookmark,
        title: 'Nothing saved yet',
        description: 'Use the bookmark button on any bounty to keep it here.',
        action: (
          <Button asChild>
            <Link to="/bounties">Browse bounties</Link>
          </Button>
        ),
      }}
    >
      {(data) => (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.items.map((b) => (
              <BountyCard key={b.id} bounty={b} />
            ))}
          </div>
          <PaginationBar
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={data.page_size}
            onPageChange={setPage}
            itemLabel="saved bounties"
          />
        </>
      )}
    </QueryView>
  )
}

export default function SavedPage() {
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'searches' ? 'searches' : 'bounties'
  const searches = useSavedSearches()
  const fresh = (searches.data ?? []).reduce((n, s) => n + s.new_count, 0)
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Workspace', to: '/app' }, { label: 'Saved' }]}
        title="Saved"
        description="Bookmarked bounties and the searches you follow."
        actions={
          <Button asChild variant="outline">
            <Link to="/bounties">
              <Search /> Find work
            </Link>
          </Button>
        }
      />
      <Tabs
        value={tab}
        onValueChange={(v) => setParams(v === 'searches' ? { tab: 'searches' } : {}, { replace: true })}
        className="gap-5"
      >
        <TabsList className="h-9">
          <TabsTrigger value="bounties" className="px-3">
            Bounties
          </TabsTrigger>
          <TabsTrigger value="searches" className="px-3">
            Searches
            {fresh > 0 && (
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-[4px] bg-primary/10 px-1 text-xs text-primary-emphasis tabular-nums">
                {formatNumber(fresh)}
                <span className="sr-only"> new</span>
              </span>
            )}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="bounties">
          <SavedBounties />
        </TabsContent>
        <TabsContent value="searches">
          <SavedSearchesPanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}
