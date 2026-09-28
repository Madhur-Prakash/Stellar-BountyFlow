import { LoaderCircle } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

/**
 * Confirmation dialog that collects a free-text reason / note / feedback.
 * `onConfirm` returns a promise; the dialog closes when it resolves.
 */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  label = 'Reason',
  confirmLabel = 'Confirm',
  destructive = false,
  required = true,
  minLength = 3,
  maxLength = 2000,
  pending = false,
  onConfirm,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  label?: string
  confirmLabel?: string
  destructive?: boolean
  required?: boolean
  minLength?: number
  maxLength?: number
  pending?: boolean
  onConfirm: (text: string) => Promise<unknown> | void
  /** Extra controls rendered above the text field (e.g. a select). */
  children?: ReactNode
}) {
  const id = useId()
  const [text, setText] = useState('')
  const [touched, setTouched] = useState(false)
  const trimmed = text.trim()
  const invalid = required ? trimmed.length < minLength : trimmed.length > 0 && trimmed.length < minLength
  const tooLong = trimmed.length > maxLength

  const close = (next: boolean) => {
    if (!next) {
      setText('')
      setTouched(false)
    }
    onOpenChange(next)
  }

  const submit = async () => {
    setTouched(true)
    if (invalid || tooLong) return
    try {
      await onConfirm(trimmed)
      close(false)
    } catch {
      /* caller surfaces the error (toast); keep the dialog open */
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
          noValidate
        >
          {children}
          <div className="space-y-2">
            <Label htmlFor={id}>
              {label}
              {!required && <span className="font-normal text-muted-foreground"> (optional)</span>}
            </Label>
            <Textarea
              id={id}
              rows={4}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={touched && (invalid || tooLong)}
              aria-describedby={touched && (invalid || tooLong) ? `${id}-err` : undefined}
            />
            {touched && (invalid || tooLong) && (
              <p id={`${id}-err`} role="alert" className="text-sm text-destructive">
                {tooLong
                  ? `Keep it under ${maxLength} characters.`
                  : `Write at least ${minLength} characters.`}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit" variant={destructive ? 'destructive' : 'default'} disabled={pending}>
              {pending && <LoaderCircle className="animate-spin" />}
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
