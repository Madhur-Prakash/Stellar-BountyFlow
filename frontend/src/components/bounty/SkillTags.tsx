import { cn } from '@/lib/utils'

/** Skills as quiet square tags. `max` keeps cards calm; the rest collapse into "+N". */
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
    <ul className={cn('flex flex-wrap gap-1', className)} aria-label={label}>
      {shown.map((s) => (
        <li
          key={s}
          className="inline-flex h-5.5 items-center rounded-[4px] border bg-surface/60 px-1.5 text-xs text-muted-foreground"
        >
          {s}
        </li>
      ))}
      {hidden > 0 && (
        <li
          className="inline-flex h-5.5 items-center px-1 text-xs text-muted-foreground"
          title={skills.slice(shown.length).join(', ')}
        >
          +{hidden}
          <span className="sr-only"> more</span>
        </li>
      )}
    </ul>
  )
}
