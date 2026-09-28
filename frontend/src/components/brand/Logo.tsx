import { cn } from '@/lib/utils'

/**
 * BountyFlow logomark: an open orbit (the escrow) with a directed flow line
 * passing through its gap (the reward moving to the contributor).
 */
export function LogoMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={cn('size-7 shrink-0', className)}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <rect width="32" height="32" rx="8" className="fill-primary" />
      <path
        d="M25.4 12.6A10 10 0 1 1 19.4 6.6"
        stroke="white"
        strokeOpacity="0.55"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path d="M9.5 22.5 22.5 9.5" stroke="white" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M15.5 9.5h7v7" stroke="white" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="9.5" cy="22.5" r="1.9" fill="white" />
    </svg>
  )
}

export function Logo({ className, markClassName }: { className?: string; markClassName?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <LogoMark className={markClassName} />
      <span className="text-[0.975rem] font-semibold tracking-tight text-foreground">BountyFlow</span>
    </span>
  )
}
