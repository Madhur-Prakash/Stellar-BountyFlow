import { BellPlus, LoaderCircle } from 'lucide-react'
import { useId, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { errorMessage } from '@/lib/api/client'
import { useCreateSavedSearch } from '@/lib/api/queries/discovery'
import type { SavedSearch } from '@/lib/api/types'

import { AlertSettingsFields, type AlertSettings } from './AlertSettingsFields'
import type { MarketplaceFilters } from './marketplace-params'
import { defaultSearchName, describeFilters, filtersToSaved } from './saved-search-params'

/** The "Save search" form. Loaded on demand by `SaveSearchButton`. */
export default function SaveSearchDialogBody({
  filters,
  open,
  onOpenChange,
  onSaved,
}: {
  filters: MarketplaceFilters
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: (search: SavedSearch) => void
}) {
  const id = useId()
  const create = useCreateSavedSearch()
  const [name, setName] = useState(() => defaultSearchName(filters))
  const [alerts, setAlerts] = useState<AlertSettings>({
    alert_frequency: 'INSTANT',
    notify_in_app: true,
    notify_email: true,
  })
  const [touched, setTouched] = useState(false)
  const saved = filtersToSaved(filters)
  const summary = describeFilters(saved)
  const invalid = !name.trim()

  const submit = () => {
    setTouched(true)
    if (invalid) return
    create.mutate(
      { name: name.trim(), filters: saved, ...alerts },
      {
        onSuccess: (search) => {
          toast.success('Search saved')
          onSaved(search)
          onOpenChange(false)
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Save this search</DialogTitle>
          <DialogDescription>
            {summary.length ? summary.join(', ') : 'Every open bounty in the marketplace.'}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <div className="space-y-2">
            <Label htmlFor={`${id}-name`}>Name</Label>
            <Input
              id={`${id}-name`}
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={touched && invalid}
              aria-describedby={touched && invalid ? `${id}-name-err` : undefined}
            />
            {touched && invalid && (
              <p id={`${id}-name-err`} role="alert" className="text-sm text-destructive">
                Give the search a name.
              </p>
            )}
          </div>
          <AlertSettingsFields value={alerts} onChange={(patch) => setAlerts((a) => ({ ...a, ...patch }))} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <LoaderCircle className="animate-spin" /> : <BellPlus />}
              Save search
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
