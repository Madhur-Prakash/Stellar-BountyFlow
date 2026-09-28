import { cn } from '@/lib/utils'

export function SkillTags({
  skills,
  max,
  className,
  label = 'Skills',
}: {
  skills: string[]
  max?: number
  className?: string
  label?: string
}) {
  if (!skills.length) return null
  const shown = max ? skills.slice(0, max) : skills
  const hidden = skills.length - shown.length
  return (
    <ul className={cn('flex flex-wrap gap-1.5', className)} aria-label={label}>
      {shown.map((s) => (
        <li
          key={s}
          className="inline-flex h-6 items-center rounded-md border bg-surface-raised px-2 text-xs text-muted-foreground"
        >
          {s}
        </li>
      ))}
      {hidden > 0 && (
        <li
          className="inline-flex h-6 items-center px-1 text-xs text-muted-foreground"
          title={skills.slice(shown.length).join(', ')}
        >
          +{hidden} more
        </li>
      )}
    </ul>
  )
}
