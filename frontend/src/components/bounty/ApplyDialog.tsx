import { GitPullRequest } from 'lucide-react'
import { lazy, Suspense, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/api/queries/auth'
import { loginPath } from '@/lib/auth-redirect'

// The form (zod schema, react-hook-form, dialog) is its own chunk, fetched when the dialog is first wanted.
const loadBody = () => import('./ApplyDialogBody')
const ApplyDialogBody = lazy(loadBody)
const preload = () => void loadBody()

type ApplyDialogProps = {
  bountyId: string
  bountyTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** The application dialog. Nothing is loaded until it opens for the first time; then it stays mounted. */
export function ApplyDialog(props: ApplyDialogProps) {
  const [wanted, setWanted] = useState(props.open)
  if (props.open && !wanted) setWanted(true)
  if (!wanted) return null
  return (
    <Suspense fallback={null}>
      <ApplyDialogBody {...props} />
    </Suspense>
  )
}

/** Apply CTA: opens the dialog for signed-in users, otherwise redirects to login with a return URL. */
export function ApplyButton({
  bountyId,
  bountyTitle,
  disabled,
  className,
}: {
  bountyId: string
  bountyTitle: string
  disabled?: boolean
  className?: string
}) {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
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
        size="lg"
        className={className}
        disabled={disabled}
        onPointerEnter={me ? preload : undefined}
        onFocus={me ? preload : undefined}
        onClick={() => (me ? setOpen(true) : navigate(loginPath(`${location.pathname}${location.search}`)))}
      >
        <GitPullRequest /> {me ? 'Apply' : 'Sign in to apply'}
      </Button>
      {me && (
        <ApplyDialog bountyId={bountyId} bountyTitle={bountyTitle} open={open} onOpenChange={onOpenChange} />
      )}
    </>
  )
}
