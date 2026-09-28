import { Filter, Info, Search, SearchX, X } from 'lucide-react'
import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyGridSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { BountyFilters } from '@/components/bounty/BountyFilters'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Reveal } from '@/components/motion/Reveal'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useDebouncedCallback } from '@/hooks/useDebounce'
import { useBounties } from '@/lib/api/queries/bounties'
import type { BountySort } from '@/lib/api/types'
import { formatNumber } from '@/lib/format'
import { scrollToTop } from '@/lib/scroll'

import {
  DEFAULT_FILTERS,
  PAGE_SIZE,
  activeFilterCount,
  effectiveSort,
  parseFilters,
  serializeFilters,
  toApiParams,
  type MarketplaceFilters,
} from './marketplace-params'

const SORT_LABELS: Record<BountySort, string> = {
  relevance: 'Best match',
  newest: 'Newest',
  deadline: 'Deadline soonest',
  reward_high: 'Reward: high to low',
  reward_low: 'Reward: low to high',
  popular: 'Most popular',
}

export default function MarketplacePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = parseFilters(searchParams)
  const [sheetOpen, setSheetOpen] = useState(false)

  /** Every filter change is written to the URL (replace, so Back leaves the page). */
  const update = useCallback(
    (patch: Partial<MarketplaceFilters>) =>
      setSearchParams((prev) => serializeFilters({ ...parseFilters(prev), ...patch }), { replace: true }),
    [setSearchParams],
  )

  // Search box: local draft, debounced into the URL.
  const [draft, setDraft] = useState(filters.q)
  const [syncedQ, setSyncedQ] = useState(filters.q)
  if (filters.q !== syncedQ) {
    // URL changed from elsewhere (Back button, reset): reflect it in the input.
    setSyncedQ(filters.q)
    if (filters.q !== draft.trim()) setDraft(filters.q)
  }
  const pushSearch = useDebouncedCallback((q: string) => update({ q, page: 1 }), 350)

  const params = toApiParams(filters)
  const { data, isPending, isError, error, refetch, isPlaceholderData, isFetching } = useBounties(params)
  const count = activeFilterCount(filters)
  const sort = effectiveSort(filters)
  const searching = !!filters.q.trim()

  const filterPanel = <BountyFilters filters={filters} onChange={update} />

  return (
    <PageContainer className="py-10 sm:py-14">
      <PageHeader
        title="Bounty marketplace"
        description="Paid tasks from requesters on BountyFlow. Use “Funded only” to see bounties whose rewards are already locked in escrow."
      />

      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            role="searchbox"
            aria-label="Search bounties"
            placeholder="Search by title, skill, or keyword"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              pushSearch(e.target.value)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') update({ q: draft, page: 1 })
            }}
            className="pr-10 pl-9"
            maxLength={200}
          />
          {draft && (
            <Button
              variant="ghost"
              size="icon-sm"
              className="absolute top-1/2 right-1 -translate-y-1/2"
              aria-label="Clear search"
              onClick={() => {
                setDraft('')
                update({ q: '', page: 1 })
              }}
            >
              <X />
            </Button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Label htmlFor="marketplace-sort" className="sr-only">
            Sort bounties
          </Label>
          <Select value={sort} onValueChange={(v) => update({ sort: v as BountySort, page: 1 })}>
            <SelectTrigger id="marketplace-sort" className="w-full md:w-52">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(SORT_LABELS) as BountySort[])
                .filter((s) => s !== 'relevance' || searching)
                .map((s) => (
                  <SelectItem key={s} value={s}>
                    {SORT_LABELS[s]}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="How sorting works">
                <Info />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-72">
              “Most popular” ranks by applications × 3 + bookmarks × 2 + views in the last 7 days, ties broken
              by newest. “Best match” ranks by search relevance and is the default while searching.
            </TooltipContent>
          </Tooltip>

          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" className="lg:hidden">
                <Filter /> Filters
                {count > 0 && (
                  <span className="rounded bg-primary/15 px-1.5 text-xs text-primary-emphasis tabular-nums">
                    {count}
                  </span>
                )}
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-[90vw] max-w-sm gap-0 p-0">
              <SheetHeader className="border-b px-5 py-4">
                <SheetTitle>Filter bounties</SheetTitle>
                <SheetDescription>Results update as you change filters.</SheetDescription>
              </SheetHeader>
              <div className="flex-1 overflow-y-auto px-5 py-5" data-lenis-prevent>
                {filterPanel}
              </div>
              <div className="border-t p-4">
                <Button className="w-full" onClick={() => setSheetOpen(false)}>
                  Show {data ? formatNumber(data.total) : ''} results
                </Button>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="hidden lg:block" aria-label="Bounty filters">
          <div
            className="sticky top-24 max-h-[calc(100dvh-7rem)] scrollbar-thin overflow-y-auto pr-2"
            data-lenis-prevent
          >
            {filterPanel}
          </div>
        </aside>

        <section aria-labelledby="results-heading" aria-busy={isFetching}>
          <div className="mb-4 flex items-center justify-between gap-2">
            <h2 id="results-heading" className="text-sm text-muted-foreground" aria-live="polite">
              {isPending
                ? 'Loading bounties…'
                : data
                  ? `${formatNumber(data.total)} ${data.total === 1 ? 'bounty' : 'bounties'}${searching ? ` for “${filters.q}”` : ''}`
                  : ''}
            </h2>
            {(count > 0 || searching || filters.sort) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraft('')
                  setSearchParams(serializeFilters(DEFAULT_FILTERS), { replace: true })
                }}
              >
                Clear all
              </Button>
            )}
          </div>

          {isError ? (
            <ErrorState error={error} title="Could not load bounties" onRetry={() => refetch()} />
          ) : !isPending && data.items.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title={count > 0 || searching ? 'No bounties match these filters' : 'No open bounties yet'}
              description={
                count > 0 || searching
                  ? 'Try removing a filter or searching for something broader.'
                  : 'Nobody has published a bounty on this network yet.'
              }
              action={
                count > 0 || searching ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setDraft('')
                      setSearchParams(serializeFilters(DEFAULT_FILTERS), { replace: true })
                    }}
                  >
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <Bones name="marketplace-results" loading={isPending} fallback={<BountyGridSkeleton count={6} />}>
              {data && (
                <>
                  <div className={isPlaceholderData ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
                    <Reveal
                      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
                      y={22}
                      stagger={0.05}
                      deps={[data.items.map((b) => b.id).join()]}
                    >
                      {data.items.map((b) => (
                        <BountyCard key={b.id} bounty={b} />
                      ))}
                    </Reveal>
                  </div>
                  <PaginationBar
                    page={data.page}
                    pages={data.pages}
                    total={data.total}
                    pageSize={data.page_size || PAGE_SIZE}
                    itemLabel="bounties"
                    onPageChange={(page) => {
                      update({ page })
                      scrollToTop()
                    }}
                  />
                </>
              )}
            </Bones>
          )}
        </section>
      </div>
    </PageContainer>
  )
}
