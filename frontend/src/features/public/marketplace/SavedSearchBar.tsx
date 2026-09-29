import { BellOff, BellRing, LoaderCircle, Pause, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api/client'
import { useMarkSavedSearchViewed, useSavedSearch, useUpdateSavedSearch } from '@/lib/api/queries/discovery'
import type { SavedSearch } from '@/lib/api/types'

import type { MarketplaceFilters } from './marketplace-params'
import { FREQUENCY_LABELS, filtersToSaved, sameFilters, savedToFilters } from './saved-search-params'

function alertSummary(s: SavedSearch): string {
  if (s.alert_frequency === 'OFF') return 'Alerts off'
  if (s.is_paused) return 'Alerts paused'
  const channels = [s.notify_in_app && 'in the app', s.notify_email && 'by email']
    .filter(Boolean)
    .join(' and ')
  const when = s.alert_frequency === 'INSTANT' ? 'Instant alerts' : FREQUENCY_LABELS[s.alert_frequency]
  return channels ? `${when} ${channels}` : when
}

/**
 * The saved search the marketplace is showing (`?saved=<id>`): its name and alert state, and, once the filters
 * have been changed, a way to update the search with them. Opening it resets "new since you last looked".
 */
export function SavedSearchBar({
  searchId,
  filters,
  onClose,
}: {
  searchId: string
  filters: MarketplaceFilters
  onClose: () => void
}) {
  const query = useSavedSearch(searchId)
  const update = useUpdateSavedSearch()
  const viewed = useMarkSavedSearchViewed()
  const marked = useRef<string | null>(null)
  const { mutate: markViewed } = viewed

  useEffect(() => {
    if (!query.data || marked.current === searchId) return
    marked.current = searchId
    markViewed(searchId)
  }, [query.data, searchId, markViewed])

  if (query.isError) return null
  if (query.isPending) {
    return (
      <div
        role="status"
        aria-label="Loading saved search"
        className="mb-4 rounded-xl border bg-card px-4 py-3"
      >
        <Skeleton className="h-5 w-56" />
      </div>
    )
  }
  const search = query.data
  const changed = !sameFilters(savedToFilters(search.filters), filters)
  const quiet = search.alert_frequency === 'OFF' || search.is_paused
  const Icon = search.alert_frequency === 'OFF' ? BellOff : search.is_paused ? Pause : BellRing

  return (
    <section
      aria-label="Saved search"
      className="mb-4 flex flex-col gap-3 rounded-xl border bg-card px-4 py-3 shadow-soft sm:flex-row sm:items-center"
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-surface text-muted-foreground">
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{search.name}</p>
          <p className="text-xs text-muted-foreground">
            {changed ? 'Filters changed since you saved this search' : alertSummary(search)}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {changed && (
          <Button
            size="sm"
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                { id: search.id, body: { filters: filtersToSaved(filters) } },
                {
                  onSuccess: () => toast.success('Saved search updated'),
                  onError: (e) => toast.error(errorMessage(e)),
                },
              )
            }
          >
            {update.isPending && <LoaderCircle className="animate-spin" />}
            Update search
          </Button>
        )}
        {quiet && !changed && (
          <Button
            size="sm"
            variant="outline"
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                {
                  id: search.id,
                  body: search.is_paused ? { is_paused: false } : { alert_frequency: 'INSTANT' },
                },
                { onError: (e) => toast.error(errorMessage(e)) },
              )
            }
          >
            Turn alerts on
          </Button>
        )}
        <Button asChild size="sm" variant="ghost" className="text-muted-foreground">
          <Link to={`/app/saved?tab=searches&open=${encodeURIComponent(search.id)}`}>Manage</Link>
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          className="text-muted-foreground"
          aria-label="Close saved search"
          onClick={onClose}
        >
          <X />
        </Button>
      </div>
    </section>
  )
}
