import { Eye, EyeOff } from 'lucide-react'
import { useState, type ComponentProps } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import { passwordStrength } from './schemas'

export function PasswordInput({ className, ...props }: ComponentProps<typeof Input>) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Input {...props} type={visible ? 'text' : 'password'} className={cn('pr-11', className)} />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="absolute top-1/2 right-0.5 -translate-y-1/2 text-muted-foreground"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
      >
        {visible ? <EyeOff /> : <Eye />}
      </Button>
    </div>
  )
}

const BAR_COLORS = ['bg-destructive', 'bg-destructive', 'bg-warning', 'bg-cyan', 'bg-success']

export function PasswordStrengthMeter({ password, id }: { password: string; id?: string }) {
  const { score, label, hints } = passwordStrength(password)
  return (
    <div id={id} className="space-y-1.5" aria-live="polite">
      <div className="grid grid-cols-4 gap-1" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className={cn('h-1 rounded-full bg-muted', password && score >= i && BAR_COLORS[score])}
          />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Password strength: <span className="font-medium text-foreground">{password ? label : '—'}</span>
        {password && hints.length > 0 && <span>. {hints[0]}</span>}
      </p>
    </div>
  )
}
