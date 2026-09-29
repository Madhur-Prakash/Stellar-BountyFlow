import {
  BellOff,
  BellRing,
  EllipsisVertical,
  ExternalLink,
  LoaderCircle,
  Pause,
  Pencil,
  Play,
  Search,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AlertSettingsFields, type AlertSettings } from '@/features/public/marketplace/AlertSettingsFields'
import {
  FREQUENCY_LABELS,
  describeFilters,
  savedSearchHref,
} from '@/features/public/marketplace/saved-search-params'
import { errorMessage } from '@/lib/api/client'
import { useDeleteSavedSearch, useSavedSearches, useUpdateSavedSearch } from '@/lib/api/queries/discovery'
import type { SavedSearch, UpdateSavedSearchRequest } from '@/lib/api/types'
import { formatDateTime, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'

import { CardQuery } from './workspace-ui'

function alertState(s: SavedSearch): { label: string; icon: typeof BellRing } {
  if (s.alert_frequency === 'OFF') return { label: 'Alerts off', icon: BellOff }
  if (s.is_paused) return { label: 'Paused', icon: Pause }
  const channels = [s.notify_in_app && 'in the app', s.notify_email && 'by email']
    .filter(Boolean)
    .join(' and ')
  const when = s.alert_frequency === 'INSTANT' ? 'Instant alerts' : FREQUENCY_LABELS[s.alert_frequency]
  return { label: channels ? `${when} ${channels}` : `${when}, no channel chosen`, icon: BellRing }
}

function RenameDialog({
  search,
  open,
  onOpenChange,
}: {
  search: SavedSearch
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const id = useId()
  const update = useUpdateSavedSearch()
  const [name, setName] = useState(search.name)
  const invalid = !name.trim()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Rename saved search</DialogTitle>
          <DialogDescription className="sr-only">Choose a new name for this saved search.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            if (invalid) return
            update.mutate(
              { id: search.id, body: { name: name.trim() } },
              { onSuccess: () => onOpenChange(false), onError: (err) => toast.error(errorMessage(err)) },
            )
          }}
        >
          <div className="space-y-2">
            <Label htmlFor={`${id}-name`}>Name</Label>
            <Input
              id={`${id}-name`}
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={invalid}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={invalid || update.isPending}>
              {update.isPending && <LoaderCircle className="animate-spin" />}
              Save name
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function AlertsDialog({
  search,
  open,
  onOpenChange,
}: {
  search: SavedSearch
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const update = useUpdateSavedSearch()
  const [alerts, setAlerts] = useState<AlertSettings>({
    alert_frequency: search.alert_frequency,
    notify_in_app: search.notify_in_app,
    notify_email: search.notify_email,
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Alerts for {search.name}</DialogTitle>
          <DialogDescription className="sr-only">
            When and how this saved search alerts you.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            update.mutate(
              { id: search.id, body: alerts },
              {
                onSuccess: () => {
                  toast.success('Alerts updated')
                  onOpenChange(false)
                },
                onError: (err) => toast.error(errorMessage(err)),
              },
            )
          }}
        >
          <AlertSettingsFields value={alerts} onChange={(patch) => setAlerts((a) => ({ ...a, ...patch }))} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending && <LoaderCircle className="animate-spin" />}
              Save alerts
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteDialog({
  search,
  open,
  onOpenChange,
}: {
  search: SavedSearch
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const remove = useDeleteSavedSearch()
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {search.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            Its alerts stop. Bounties you bookmarked are not affected.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={(e) => {
              e.preventDefault()
              remove.mutate(search.id, {
                onSuccess: () => {
                  toast.success('Saved search deleted')
                  onOpenChange(false)
                },
                onError: (err) => toast.error(errorMessage(err)),
              })
            }}
          >
            {remove.isPending && <LoaderCircle className="animate-spin" />}
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

type Dialogs = 'rename' | 'alerts' | 'delete' | null

function SavedSearchRow({ search, highlighted }: { search: SavedSearch; highlighted: boolean }) {
  const [dialog, setDialog] = useState<Dialogs>(null)
  const update = useUpdateSavedSearch()
  const filters = describeFilters(search.filters)
  const state = alertState(search)
  const href = savedSearchHref(search)
  const titleId = `saved-search-${search.id}`
  const patch = (body: UpdateSavedSearchRequest, done: string) =>
    update.mutate(
      { id: search.id, body },
      { onSuccess: () => toast.success(done), onError: (e) => toast.error(errorMessage(e)) },
    )
  const close = (open: boolean) => !open && setDialog(null)

  return (
    <li
      id={titleId + '-row'}
      className={cn(
        'flex flex-col gap-3 px-4 py-4 transition-colors sm:flex-row sm:items-center sm:px-5',
        highlighted && 'bg-primary/5',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 id={titleId} className="text-sm font-semibold">
            <Link to={href} className="hover:underline focus-visible:underline">
              {search.name}
            </Link>
          </h3>
          {search.new_count > 0 && <Badge variant="info">{formatNumber(search.new_count)} new</Badge>}
        </div>
        <p className="mt-1 text-[0.8125rem] text-muted-foreground">
          {filters.length ? filters.join(', ') : 'Every open bounty'}
        </p>
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          <state.icon className="size-3.5 shrink-0" aria-hidden />
          <span>
            {state.label}
            {search.alert_frequency !== 'OFF' && !search.is_paused && search.next_digest_at && (
              <>
                , next on{' '}
                <time dateTime={search.next_digest_at}>{formatDateTime(search.next_digest_at)}</time>
              </>
            )}
          </span>
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button asChild variant="outline" size="sm">
          <Link to={href}>
            <ExternalLink /> Open in marketplace
          </Link>
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`More actions for ${search.name}`}>
              <EllipsisVertical />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem onSelect={() => setDialog('rename')}>
              <Pencil /> Rename
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to={href}>
                <SlidersHorizontal /> Edit filters
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setDialog('alerts')}>
              <BellRing /> Alert settings
            </DropdownMenuItem>
            {search.alert_frequency !== 'OFF' && (
              <DropdownMenuItem
                onSelect={() =>
                  patch(
                    { is_paused: !search.is_paused },
                    search.is_paused ? 'Alerts resumed' : 'Alerts paused',
                  )
                }
              >
                {search.is_paused ? <Play /> : <Pause />}
                {search.is_paused ? 'Resume alerts' : 'Pause alerts'}
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onSelect={() => setDialog('delete')}>
              <Trash2 /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {dialog === 'rename' && <RenameDialog search={search} open onOpenChange={close} />}
      {dialog === 'alerts' && <AlertsDialog search={search} open onOpenChange={close} />}
      {dialog === 'delete' && <DeleteDialog search={search} open onOpenChange={close} />}
    </li>
  )
}

/** The signed-in user's saved searches: new matches, alert state, and every way to manage them. */
export function SavedSearchesPanel() {
  const query = useSavedSearches()
  const [params] = useSearchParams()
  const open = params.get('open')
  const ready = !!query.data

  useEffect(() => {
    if (!ready || !open) return
    document.getElementById(`saved-search-${open}-row`)?.scrollIntoView({ block: 'center' })
  }, [ready, open])

  return (
    <div className="rounded-xl border bg-card shadow-soft">
      <CardQuery
        query={query}
        skeleton="app-saved-searches"
        rows={3}
        isEmpty={(d) => d.length === 0}
        empty={{
          icon: Search,
          title: 'No saved searches',
          description: 'Save a marketplace search to get alerts when new bounties match it.',
          action: (
            <Button asChild>
              <Link to="/bounties">Search bounties</Link>
            </Button>
          ),
        }}
      >
        {(searches) => (
          <ul className="divide-y" aria-label="Saved searches">
            {searches.map((s) => (
              <SavedSearchRow key={s.id} search={s} highlighted={s.id === open} />
            ))}
          </ul>
        )}
      </CardQuery>
    </div>
  )
}
