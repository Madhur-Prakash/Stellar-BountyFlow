import { Bookmark } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyGridSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Reveal } from '@/components/motion/Reveal'
import { Button } from '@/components/ui/button'
import { useSavedBounties } from '@/lib/api/queries/bounties'

export default function SavedPage() {
  const [page, setPage] = useState(1)
  const query = useSavedBounties({ page, page_size: 12 })
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Saved bounties" description="Bounties you bookmarked to come back to." />
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
            <Reveal
              className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
              deps={[data.items.map((b) => b.id).join()]}
            >
              {data.items.map((b) => (
                <BountyCard key={b.id} bounty={b} />
              ))}
            </Reveal>
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
    </div>
  )
}
