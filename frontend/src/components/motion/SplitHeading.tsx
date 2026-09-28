import { useRef, type ElementType, type ReactNode } from 'react'

import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap, SplitText, useGSAP } from '@/lib/gsap'
import { cn } from '@/lib/utils'

type Props = {
  as?: ElementType
  id?: string
  className?: string
  children: ReactNode
  /** `load`: plays as soon as it mounts (hero). `scroll`: plays when it enters the viewport. */
  trigger?: 'load' | 'scroll'
  /**
   * Characters also widen from compressed to the heading's own width as they rise: the display face is a width-axis
   * variable font, so the type itself expands, like value being unlocked.
   */
  expand?: boolean
  delay?: number
}

/**
 * A heading whose characters rise out of masked lines. SplitText re-splits on resize and after fonts load
 * (`autoSplit`), and keeps the accessible name intact (`aria: 'auto'`). Without motion it is a plain heading.
 */
export function SplitHeading({
  as: Tag = 'h2',
  id,
  className,
  children,
  trigger = 'scroll',
  expand = false,
  delay = 0,
}: Props) {
  const ref = useRef<HTMLElement>(null)

  useGSAP(
    () => {
      const el = ref.current
      if (!el || !motionAllowed()) return
      SplitText.create(el, {
        type: 'lines,chars',
        mask: 'lines',
        linesClass: 'split-line',
        autoSplit: true,
        aria: 'auto',
        onSplit: (self) =>
          gsap.from(self.chars, {
            yPercent: 118,
            ...(expand ? { fontStretch: '52%' } : {}),
            duration: expand ? 1.1 : 0.85,
            stagger: expand ? 0.022 : 0.012,
            delay,
            ease: 'bf-settle',
            ...(trigger === 'scroll' ? { scrollTrigger: { trigger: el, start: 'top 88%', once: true } } : {}),
          }),
      })
    },
    { scope: ref, dependencies: [children, expand, trigger], revertOnUpdate: true },
  )

  return (
    <Tag ref={ref} id={id} className={cn(className)}>
      {children}
    </Tag>
  )
}
