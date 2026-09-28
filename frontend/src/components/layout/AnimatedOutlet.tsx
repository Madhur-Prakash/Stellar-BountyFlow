import { useLocation, useOutlet } from 'react-router'

import { cn } from '@/lib/utils'

/**
 * Route-level page entrance: a short fade with a 4px rise, done in CSS on the keyed wrapper. There is no exit
 * animation, so navigation never waits. Under reduced motion the global rule in index.css removes it.
 */
export function AnimatedOutlet({ className }: { className?: string }) {
  const outlet = useOutlet()
  const { pathname } = useLocation()

  return (
    <div
      key={pathname}
      className={cn('animate-in duration-300 ease-out fade-in-0 slide-in-from-bottom-1', className)}
    >
      {outlet}
    </div>
  )
}
