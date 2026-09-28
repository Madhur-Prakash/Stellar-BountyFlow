import type { ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { CircleAlert } from 'lucide-react'

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description && <p className="mt-2 text-sm text-muted-foreground">{description}</p>}
      <div className="mt-8">{children}</div>
      {footer && <div className="mt-8 text-center text-sm text-muted-foreground">{footer}</div>}
    </div>
  )
}

export function FormErrorAlert({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <Alert variant="destructive" aria-live="assertive">
      <CircleAlert />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
