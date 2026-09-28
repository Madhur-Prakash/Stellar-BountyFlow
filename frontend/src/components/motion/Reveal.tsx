import { useRef, type ElementType, type ReactNode } from 'react'

import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap, ScrollTrigger, useGSAP } from '@/lib/gsap'

type Props = {
  as?: ElementType
  className?: string
  children: ReactNode
  /** Which descendants animate. Default: the direct children. */
  selector?: string
  /** Distance each item rises, in px. */
  y?: number
  stagger?: number
  /** Re-run when these change (e.g. a list's item keys), so newly rendered items animate in too. */
  deps?: unknown[]
  [key: string]: unknown
}

/**
 * Items rise into place in small groups as they scroll into view (ScrollTrigger.batch), each group staggered.
 * Items already on screen animate immediately. An item animates once: when the list changes (a page of new
 * results, an item removed), only elements not seen before rise in. Without motion, nothing is hidden at any point.
 */
export function Reveal({
  as: Tag = 'div',
  className,
  children,
  selector = ':scope > *',
  y = 28,
  stagger = 0.07,
  deps = [],
  ...rest
}: Props) {
  const ref = useRef<HTMLElement>(null)
  const revealed = useRef(new WeakSet<Element>())

  useGSAP(
    () => {
      const root = ref.current
      if (!root || !motionAllowed()) return
      const targets = Array.from(root.querySelectorAll<HTMLElement>(selector)).filter(
        (el) => !revealed.current.has(el),
      )
      if (targets.length === 0) return
      gsap.set(targets, { autoAlpha: 0, y })
      ScrollTrigger.batch(targets, {
        start: 'top 97%',
        once: true,
        onEnter: (batch) => {
          batch.forEach((el) => revealed.current.add(el))
          gsap.to(batch, {
            autoAlpha: 1,
            y: 0,
            duration: 0.75,
            stagger,
            ease: 'bf-settle',
            overwrite: true,
            clearProps: 'transform,opacity,visibility',
          })
        },
      })
    },
    { scope: ref, dependencies: deps, revertOnUpdate: true },
  )

  return (
    <Tag ref={ref} className={className} {...rest}>
      {children}
    </Tag>
  )
}
