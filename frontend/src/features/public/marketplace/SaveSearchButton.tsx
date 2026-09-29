import { BellPlus } from 'lucide-react'
import { lazy, Suspense, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/api/queries/auth'
import type { SavedSearch } from '@/lib/api/types'
import { loginPath } from '@/lib/auth-redirect'
import { cn } from '@/lib/utils'

import type { MarketplaceFilters } from './marketplace-params'

// The form is its own chunk, fetched when the dialog is first wanted.
const loadBody = () => import('./SaveSearchDialogBody')
const SaveSearchDialogBody = lazy(loadBody)
const preload = () => void loadBody()

/** "Save search": saves the marketplace's current query for signed-in users, otherwise sends them to login. */
export function SaveSearchButton({
  filters,
  onSaved,
  className,
}: {
  filters: MarketplaceFilters
  onSaved: (search: SavedSearch) => void
  className?: string
}) {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const [wanted, setWanted] = useState(false)
  const [session, setSession] = useState(0) // a fresh form (and default name) each time it opens
  const trigger = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const onOpenChange = (next: boolean) => {
    setOpen(next)
    if (!next) requestAnimationFrame(() => trigger.current?.focus())
  }

  return (
    <>
      <Button
        ref={trigger}
        variant="outline"
        size="sm"
        className={cn('rounded-full bg-card dark:bg-card', className)}
        onPointerEnter={me ? preload : undefined}
        onFocus={me ? preload : undefined}
        onClick={() => {
          if (!me) {
            navigate(loginPath(`${location.pathname}${location.search}`))
            return
          }
          setWanted(true)
          setSession((s) => s + 1)
          setOpen(true)
        }}
      >
        <BellPlus /> Save search
      </Button>
      {wanted && (
        <Suspense fallback={null}>
          <SaveSearchDialogBody
            key={session}
            filters={filters}
            open={open}
            onOpenChange={onOpenChange}
            onSaved={onSaved}
          />
        </Suspense>
      )}
    </>
  )
}
