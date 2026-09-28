import { LayoutGrid, List, Search, SearchX, SlidersHorizontal, X } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { BountyCard } from '@/components/bounty/BountyCard'
import { BountyGridSkeleton } from '@/components/bounty/BountyCardSkeleton'
import { BountyFilters } from '@/components/bounty/BountyFilters'
import { BountyList, BountyListSkeleton } from '@/components/bounty/BountyRow'
import { Bones } from '@/components/layout/Bones'
import { EmptyState } from '@/components/layout/EmptyState'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageContainer } from '@/components/layout/PageContainer'
import { PaginationBar } from '@/components/layout/PaginationBar'
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
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useDebouncedCallback } from '@/hooks/useDebounce'
import { useBounties } from '@/lib/api/queries/bounties'
import type { BountySort } from '@/lib/api/types'
import { formatNumber } from '@/lib/format'
import { scrollToTop } from '@/lib/scroll'
import { cn } from '@/lib/utils'
import { useUiPrefs } from '@/stores/ui-prefs'

import {
  DEFAULT_FILTERS,
  FILTER_RESET,
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

/** One segment of the grid/list switch: a pill inside the pill, filled when selected. */
const VIEW_ITEM =
  'h-9 w-9 min-w-9 rounded-full px-0 text-muted-foreground data-[state=on]:bg-foreground data-[state=on]:text-background data-[state=on]:hover:bg-foreground data-[state=on]:hover:text-background'

export default function MarketplacePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = parseFilters(searchParams)
  const [sheetOpen, setSheetOpen] = useState(false)
  const view = useUiPrefs((s) => s.marketplaceView)
  const setView = useUiPrefs((s) => s.setMarketplaceView)

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
  const narrowed = count > 0 || searching

  const clearAll = () => {
    setDraft('')
    setSearchParams(serializeFilters(DEFAULT_FILTERS), { replace: true })
  }

  return (
    <PageContainer className="pt-10 pb-16 sm:pt-16 sm:pb-20">
      <header className="pb-8 sm:pb-10">
        <h1 className="font-display text-[2.25rem] leading-[1.02] sm:text-[3rem]">Bounty marketplace</h1>
        <p className="mt-3 max-w-2xl text-base text-muted-foreground sm:text-lg">
          Paid tasks from requesters on BountyFlow.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)] lg:items-start">
        <aside className="hidden lg:sticky lg:top-20 lg:block" aria-label="Bounty filters">
          <div
            className="max-h-[calc(100dvh-6rem)] scrollbar-thin overflow-y-auto rounded-xl border bg-card"
            data-lenis-prevent
          >
            <BountyFilters filters={filters} onChange={update} />
          </div>
        </aside>

        <section aria-labelledby="results-heading" aria-busy={isFetching} className="min-w-0">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative min-w-0 flex-1">
              <Search
                className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                type="search"
                role="searchbox"
                aria-label="Search bounties"
                placeholder="Search by title, skill or keyword"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value)
                  pushSearch(e.target.value)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') update({ q: draft, page: 1 })
                }}
                className="h-11 rounded-full bg-card pr-11 pl-10.5 shadow-none max-lg:h-11 dark:bg-card [&::-webkit-search-cancel-button]:hidden"
                maxLength={200}
              />
              {draft && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-full text-muted-foreground"
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
              <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
                <SheetTrigger asChild>
                  <Button
                    variant="outline"
                    className="h-11 rounded-full bg-card px-4 max-lg:h-11 lg:hidden dark:bg-card"
                  >
                    <SlidersHorizontal /> Filters
                    {count > 0 && (
                      <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-[4px] bg-primary/10 px-1 text-xs text-primary-emphasis tabular-nums">
                        {count}
                        <span className="sr-only"> active</span>
                      </span>
                    )}
                  </Button>
                </SheetTrigger>
                <SheetContent side="left" className="w-[90vw] max-w-sm gap-0 p-0">
                  <SheetHeader className="border-b px-4 py-3.5">
                    <SheetTitle>Filter bounties</SheetTitle>
                    <SheetDescription className="sr-only">Results update as filters change.</SheetDescription>
                  </SheetHeader>
                  <div className="flex-1 overflow-y-auto" data-lenis-prevent>
                    <BountyFilters filters={filters} onChange={update} header={false} />
                  </div>
                  <div className="flex gap-2 border-t p-4">
                    <Button
                      variant="outline"
                      className="flex-1"
                      disabled={count === 0}
                      onClick={() => update({ ...FILTER_RESET, page: 1 })}
                    >
                      Reset
                    </Button>
                    <Button className="flex-1" onClick={() => setSheetOpen(false)}>
                      Show {data ? formatNumber(data.total) : ''} results
                    </Button>
                  </div>
                </SheetContent>
              </Sheet>

              <Label htmlFor="marketplace-sort" className="sr-only">
                Sort bounties
              </Label>
              <Select value={sort} onValueChange={(v) => update({ sort: v as BountySort, page: 1 })}>
                <SelectTrigger
                  id="marketplace-sort"
                  className="h-11! min-w-0 flex-1 rounded-full pr-3 pl-4 sm:w-52 sm:flex-none dark:bg-card"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  {(Object.keys(SORT_LABELS) as BountySort[])
                    .filter((s) => s !== 'relevance' || searching)
                    .map((s) => (
                      <SelectItem key={s} value={s}>
                        {SORT_LABELS[s]}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>

              <ToggleGroup
                type="single"
                spacing={0.5}
                value={view}
                onValueChange={(v) => v && setView(v as 'grid' | 'list')}
                aria-label="Layout"
                className="h-11 shrink-0 rounded-full border border-input bg-card p-0.75"
              >
                <ToggleGroupItem value="grid" aria-label="Grid view" className={VIEW_ITEM}>
                  <LayoutGrid />
                </ToggleGroupItem>
                <ToggleGroupItem value="list" aria-label="List view" className={VIEW_ITEM}>
                  <List />
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
          </div>

          <div className="mt-5 mb-3 flex min-h-8 items-center justify-between gap-2">
            <h2 id="results-heading" className="label-mono" aria-live="polite">
              {isPending
                ? 'Loading bounties…'
                : data
                  ? `${formatNumber(data.total)} ${data.total === 1 ? 'bounty' : 'bounties'}${searching ? ` for “${filters.q}”` : ''}`
                  : ''}
            </h2>
            {(narrowed || filters.sort) && (
              <Button
                variant="ghost"
                size="sm"
                className="-mr-2 rounded-full text-muted-foreground"
                onClick={clearAll}
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
              title={narrowed ? 'No bounties match these filters' : 'No open bounties yet'}
              description={narrowed ? 'Try fewer filters or a broader search.' : undefined}
              action={
                narrowed ? (
                  <Button variant="outline" onClick={clearAll}>
                    Clear filters
                  </Button>
                ) : (
                  <Button asChild>
                    <Link to="/app/bounties/create">Post a bounty</Link>
                  </Button>
                )
              }
            />
          ) : view === 'list' ? (
            <Bones
              name="marketplace-results-list"
              loading={isPending}
              fallback={<BountyListSkeleton count={8} />}
            >
              {data && (
                <>
                  <div className={cn('transition-opacity', isPlaceholderData && 'opacity-60')}>
                    <BountyList bounties={data.items} label="Bounty results" />
                  </div>
                  <Pagination data={data} onPageChange={(page) => update({ page })} />
                </>
              )}
            </Bones>
          ) : (
            <Bones name="marketplace-results" loading={isPending} fallback={<BountyGridSkeleton count={6} />}>
              {data && (
                <>
                  <div className={cn('transition-opacity', isPlaceholderData && 'opacity-60')}>
                    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                      {data.items.map((b) => (
                        <BountyCard key={b.id} bounty={b} />
                      ))}
                    </div>
                  </div>
                  <Pagination data={data} onPageChange={(page) => update({ page })} />
                </>
              )}
            </Bones>
          )}
        </section>
      </div>
    </PageContainer>
  )
}

function Pagination({
  data,
  onPageChange,
}: {
  data: { page: number; pages: number; total: number; page_size: number }
  onPageChange: (page: number) => void
}) {
  return (
    <PaginationBar
      page={data.page}
      pages={data.pages}
      total={data.total}
      pageSize={data.page_size || PAGE_SIZE}
      itemLabel="bounties"
      onPageChange={(page) => {
        onPageChange(page)
        scrollToTop()
      }}
    />
  )
}
