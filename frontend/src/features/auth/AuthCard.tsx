import { CircleAlert, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

const TONES = {
  primary: 'bg-primary/10 text-primary-emphasis',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/12 text-warning',
  destructive: 'bg-destructive/10 text-destructive',
} as const

/**
 * One auth screen: a centred title and subtitle, the form (or the screen's actions) in a card, and the link to the
 * other auth screen below it. Status screens (email sent, link expired…) add an icon above the title.
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
        className="mb-7 text-center"
        role={live}
        aria-live={live === 'alert' ? 'assertive' : live === 'status' ? 'polite' : undefined}
      >
        {Icon && (
          <div
            className={cn('mx-auto mb-4 flex size-10 items-center justify-center rounded-lg', TONES[tone])}
          >
            <Icon className={cn('size-5', iconClassName)} aria-hidden />
          </div>
        )}
        <h1 className="font-display text-[1.625rem] leading-tight">{title}</h1>
        {description && (
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">{description}</p>
        )}
      </div>
      {children && <div className="rounded-2xl border bg-card p-5 shadow-lift sm:p-6">{children}</div>}
      {footer && <p className="mt-6 text-center text-sm text-muted-foreground">{footer}</p>}
    </div>
  )
}

/** Link styling for the "New to BountyFlow? Create an account" line under the card. */
export const AUTH_LINK = 'font-medium text-primary-emphasis underline-offset-4 hover:underline'

export function FormErrorAlert({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <Alert variant="destructive" aria-live="assertive">
      <CircleAlert />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
