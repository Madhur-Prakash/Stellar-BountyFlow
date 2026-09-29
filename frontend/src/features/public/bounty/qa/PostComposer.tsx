import { LoaderCircle } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { QA_BODY_MAX } from '@/lib/api/types'
import { cn } from '@/lib/utils'

/** A Markdown text box with its own length checks, used to ask, reply and edit. */
export function PostComposer({
  label,
  hideLabel = false,
  submitLabel,
  submitIcon,
  initialValue = '',
  minLength,
  rows = 3,
  placeholder,
  pending,
  autoFocus = false,
  onSubmit,
  onCancel,
  className,
}: {
  label: string
  hideLabel?: boolean
  submitLabel: string
  submitIcon?: ReactNode
  initialValue?: string
  minLength: number
  rows?: number
  placeholder?: string
  pending: boolean
  autoFocus?: boolean
  /** Resolves when saved; the box then clears (unless editing). Rejects to keep the text. */
  onSubmit: (body: string) => Promise<unknown>
  onCancel?: () => void
  className?: string
}) {
  const id = useId()
  const [text, setText] = useState(initialValue)
  const [error, setError] = useState<string | null>(null)
  const trimmed = text.trim()

  const submit = async () => {
    if (trimmed.length < minLength) {
      setError(`Write at least ${minLength} characters.`)
      return
    }
    if (trimmed.length > QA_BODY_MAX) {
      setError(`Keep it under ${QA_BODY_MAX.toLocaleString('en-US')} characters.`)
      return
    }
    setError(null)
    try {
      await onSubmit(trimmed)
      if (!initialValue) setText('')
    } catch {
      /* the caller shows the error; the text stays */
    }
  }

  return (
    <form
      className={cn('space-y-2', className)}
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <Label htmlFor={id} className={cn(hideLabel && 'sr-only')}>
        {label}
      </Label>
      <Textarea
        id={id}
        rows={rows}
        value={text}
        placeholder={placeholder}
        autoFocus={autoFocus}
        maxLength={QA_BODY_MAX + 200}
        onChange={(e) => {
          setText(e.target.value)
          if (error) setError(null)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            void submit()
          }
        }}
        aria-invalid={!!error}
        aria-describedby={`${id}-hint${error ? ` ${id}-err` : ''}`}
      />
      {error && (
        <p id={`${id}-err`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          Markdown supported.
        </p>
        <div className="flex gap-2">
          {onCancel && (
            <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
              Cancel
            </Button>
          )}
          <Button type="submit" size="sm" disabled={pending}>
            {pending ? <LoaderCircle className="animate-spin" /> : submitIcon}
            {submitLabel}
          </Button>
        </div>
      </div>
    </form>
  )
}
