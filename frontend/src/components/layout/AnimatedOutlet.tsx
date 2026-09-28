import { useRef } from 'react'
import { useLocation, useOutlet } from 'react-router'

import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap, useGSAP } from '@/lib/gsap'

/**
 * Route-level page entrance: a short fade with a 6px rise. There is no exit animation, so
 * navigation never waits. Transforms are cleared afterwards so sticky and fixed descendants behave normally.
 */
export function AnimatedOutlet({ className }: { className?: string }) {
  const outlet = useOutlet()
  const { pathname } = useLocation()
  const ref = useRef<HTMLDivElement>(null)

  useGSAP(
    () => {
      if (!ref.current || !motionAllowed()) return
      gsap.fromTo(
        ref.current,
        { autoAlpha: 0, y: 6 },
        { autoAlpha: 1, y: 0, duration: 0.32, ease: 'power2.out', clearProps: 'transform,opacity,visibility' },
      )
    },
    { dependencies: [pathname], scope: ref, revertOnUpdate: true },
  )

  return (
    <div key={pathname} ref={ref} className={className}>
      {outlet}
    </div>
  )
}
