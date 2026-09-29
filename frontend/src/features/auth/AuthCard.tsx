import { CircleAlert, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

const TONES = {
  primary: 'border-primary/20 bg-primary/10 text-primary-emphasis',
  success: 'border-success/20 bg-success/10 text-success',
  warning: 'border-warning/25 bg-warning/12 text-warning',
  destructive: 'border-destructive/20 bg-destructive/10 text-destructive',
} as const

/**
 * One auth screen: a centred title and subtitle on the canvas, the form (or the screen's actions) in a single
 * card below them, and the link to the other auth screen under that. Nothing frames the card but the canvas —
 * the form and its one action should be the only things asking for attention. Status screens (email sent, link
 * expired…) add an icon above the title.
 */
export function AuthCard({
  title,
  description,
  icon: Icon,
  iconClassName,
  tone = 'primary',
  live,
  children,
  footer,
}: {
  title: string
  description?: ReactNode
  icon?: LucideIcon
  iconClassName?: string
  tone?: keyof typeof TONES
  /** Announce the title and subtitle when they appear (an error, or a status that changes on its own). */
  live?: 'alert' | 'status'
  children?: ReactNode
  footer?: ReactNode
}) {
  return (
    <div>
      <div
        className="mx-auto mb-8 max-w-md text-center"
        role={live}
        aria-live={live === 'alert' ? 'assertive' : live === 'status' ? 'polite' : undefined}
      >
        {Icon && (
          <div
            className={cn(
              'mx-auto mb-5 flex size-11 items-center justify-center rounded-xl border',
              TONES[tone],
            )}
          >
            <Icon className={cn('size-5', iconClassName)} aria-hidden />
          </div>
        )}
        <h1 className="font-display text-[2rem] leading-[1.08] sm:text-[2.375rem]">{title}</h1>
        {description && (
          <p className="mx-auto mt-3 max-w-sm text-[0.9375rem] leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {children && (
        <div className="mx-auto max-w-104 rounded-2xl border bg-card p-6 shadow-lift sm:p-8">{children}</div>
      )}
      {footer && <p className="mt-8 text-center text-sm text-muted-foreground">{footer}</p>}
    </div>
  )
}

/** Link styling for the "New to BountyFlow? Create an account" line under the card. */
export const AUTH_LINK =
  'font-medium text-foreground underline decoration-border underline-offset-4 transition-colors hover:decoration-foreground'

export function FormErrorAlert({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <Alert variant="destructive" aria-live="assertive">
      <CircleAlert />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
