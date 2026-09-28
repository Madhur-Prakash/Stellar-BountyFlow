import { FileCheck2, RotateCcw } from 'lucide-react'
import { lazy, Suspense, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import type { Submission } from '@/lib/api/types'

// The form (zod schema, react-hook-form, dialog) is its own chunk, fetched when the dialog is first wanted.
const loadBody = () => import('./SubmitWorkDialogBody')
const SubmitWorkDialogBody = lazy(loadBody)
const preload = () => void loadBody()

type SubmitWorkDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  bountyId: string
  bountyTitle: string
  /** Present in revise mode. */
  submission?: Submission | null
}

/**
 * Deliver work for an assigned bounty, or send a revision. Nothing is loaded until the dialog opens for the
 * first time; then it stays mounted.
 */
export function SubmitWorkDialog(props: SubmitWorkDialogProps) {
  const [wanted, setWanted] = useState(props.open)
  if (props.open && !wanted) setWanted(true)
  if (!wanted) return null
  return (
    <Suspense fallback={null}>
      <SubmitWorkDialogBody {...props} />
    </Suspense>
  )
}

/** Button + dialog pair. */
export function SubmitWorkButton({
  bountyId,
  bountyTitle,
  submission,
  className,
  size = 'lg',
  variant = 'default',
}: {
  bountyId: string
  bountyTitle: string
  submission?: Submission | null
  className?: string
  size?: 'default' | 'sm' | 'lg'
  variant?: 'default' | 'outline'
}) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const onOpenChange = (next: boolean) => {
    setOpen(next)
    // The dialog has no Radix trigger, so hand focus back to the button ourselves.
    if (!next) requestAnimationFrame(() => trigger.current?.focus())
  }
  return (
    <>
      <Button
        ref={trigger}
        size={size}
        variant={variant}
        className={className}
        onPointerEnter={preload}
        onFocus={preload}
        onClick={() => setOpen(true)}
      >
        {submission ? <RotateCcw /> : <FileCheck2 />}
        {submission ? 'Send revision' : 'Submit work'}
      </Button>
      <SubmitWorkDialog
        open={open}
        onOpenChange={onOpenChange}
        bountyId={bountyId}
        bountyTitle={bountyTitle}
        submission={submission}
      />
    </>
  )
}
