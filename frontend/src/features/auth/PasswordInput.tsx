import { Eye, EyeOff, LockKeyhole, type LucideIcon } from 'lucide-react'
import { useState, type ComponentProps } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import { PASSWORD_MIN, passwordStrength } from './schemas'

const LEAD_ICON =
  'pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground transition-colors peer-focus-visible:text-foreground peer-aria-invalid:text-destructive'

/**
 * A 36px field with a leading icon. Every prop goes to the input, so it works inside `FormControl` like `Input`.
 */
export function IconInput({
  icon: Icon,
  className,
  ...props
}: ComponentProps<typeof Input> & { icon: LucideIcon }) {
  return (
    <div className="relative">
      <Input {...props} className={cn('peer bg-card pl-9', className)} />
      <Icon className={LEAD_ICON} aria-hidden />
    </div>
  )
}

export function PasswordInput({ className, ...props }: ComponentProps<typeof Input>) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Input
        {...props}
        type={visible ? 'text' : 'password'}
        className={cn('peer bg-card pr-10 pl-9', className)}
      />
      <LockKeyhole className={LEAD_ICON} aria-hidden />
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="absolute top-1/2 right-1 -translate-y-1/2 text-muted-foreground"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </Button>
    </div>
  )
}

const BAR_COLORS = ['bg-destructive', 'bg-destructive', 'bg-warning', 'bg-cyan', 'bg-success']

export function PasswordStrengthMeter({ password, id }: { password: string; id?: string }) {
  const { score, label, hints } = passwordStrength(password)
  // Hidden until the user starts typing; the live region then announces the strength as it changes.
  return (
    <div id={id} aria-live="polite" className="empty:hidden">
      {password ? (
        <div className="space-y-1.5">
          <div className="grid grid-cols-4 gap-1" aria-hidden>
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className={cn('h-1 rounded-full bg-muted transition-colors', score >= i && BAR_COLORS[score])}
              />
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Password strength: <span className="font-medium text-foreground">{label}</span>
            {hints.length > 0 && <span>. {hints[0]}</span>}
          </p>
        </div>
      ) : null}
    </div>
  )
}

/** Placeholder for new-password fields. */
export const NEW_PASSWORD_HINT = `At least ${PASSWORD_MIN} characters`
