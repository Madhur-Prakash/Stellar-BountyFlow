import { Flag } from 'lucide-react'
import { lazy, Suspense, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/api/queries/auth'
import { loginPath } from '@/lib/auth-redirect'

// The form is its own chunk, fetched when the dialog is first wanted.
const loadBody = () => import('./ReportDialogBody')
const ReportDialogBody = lazy(loadBody)
const preload = () => void loadBody()

/** "Report" action: opens the report dialog for signed-in users, otherwise sends them to login. */
export function ReportButton({ bountyId }: { bountyId: string }) {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const [wanted, setWanted] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const onOpenChange = (next: boolean) => {
    setOpen(next)
    // The dialog has no Radix trigger, so hand focus back to the button ourselves.
    if (!next) requestAnimationFrame(() => trigger.current?.focus())
  }

  return (
    <>
      <Button
        ref={trigger}
        variant="ghost"
        onPointerEnter={me ? preload : undefined}
        onFocus={me ? preload : undefined}
        onClick={() => {
          if (!me) {
            navigate(loginPath(`${location.pathname}${location.search}`))
            return
          }
          setWanted(true)
          setOpen(true)
        }}
        className="text-muted-foreground"
      >
        <Flag /> Report
      </Button>
      {wanted && (
        <Suspense fallback={null}>
          <ReportDialogBody bountyId={bountyId} open={open} onOpenChange={onOpenChange} />
        </Suspense>
      )}
    </>
  )
}
