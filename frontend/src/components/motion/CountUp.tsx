import { useRef } from 'react'

import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap, useGSAP } from '@/lib/gsap'
import { formatNumber } from '@/lib/format'

/**
 * A figure that counts up from zero the first time it scrolls into view. Later changes (live data refetching)
 * tween briefly from the value already on screen instead of starting over. The final value is what is rendered
 * (and what assistive technology reads); the count only replaces the text while it runs.
 */
export function CountUp({
  value,
  format = (n: number) => formatNumber(Math.round(n)),
  display,
  className,
  duration = 1.4,
}: {
  value: number
  format?: (n: number) => string
  /** Exact text for the final value when `format(value)` would not reproduce it (decimal amounts). */
  display?: string
  className?: string
  duration?: number
}) {
  const final = display ?? format(value)
  const ref = useRef<HTMLSpanElement>(null)
  // The value on screen once the first count has run; null until then.
  const shown = useRef<number | null>(null)

  useGSAP(
    () => {
      const el = ref.current
      if (!el || !motionAllowed() || !Number.isFinite(value)) return
      const from = shown.current
      if (from === value) return
      if (from === null && value === 0) {
        shown.current = 0
        return
      }
      const counter = { n: from ?? 0 }
      el.textContent = format(counter.n)
      gsap.to(counter, {
        n: value,
        duration: from === null ? duration : 0.6,
        ease: 'power3.out',
        ...(from === null ? { scrollTrigger: { trigger: el, start: 'top 92%', once: true } } : {}),
        onUpdate: () => {
          el.textContent = format(counter.n)
        },
        onComplete: () => {
          el.textContent = final
          shown.current = value
        },
      })
      return () => {
        el.textContent = final
      }
    },
    { scope: ref, dependencies: [value, final], revertOnUpdate: true },
  )

  return (
    <span ref={ref} className={className}>
      {final}
    </span>
  )
}
