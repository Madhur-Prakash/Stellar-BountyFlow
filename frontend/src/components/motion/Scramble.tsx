import { ScrambleTextPlugin } from 'gsap/ScrambleTextPlugin'
import { useRef } from 'react'

import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap, useGSAP } from '@/lib/gsap'
import { cn } from '@/lib/utils'

gsap.registerPlugin(ScrambleTextPlugin)

/** Stellar addresses, contract ids and hashes are base32 / hex; scrambling through that alphabet reads as "data". */
const LEDGER_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'

/**
 * Machine data (a contract id, a transaction hash) that resolves out of scrambled characters the first time it
 * is seen. The real text is always in the DOM before and after; only the visible glyphs churn briefly.
 */
export function Scramble({
  text,
  className,
  chars = LEDGER_CHARS,
}: {
  text: string
  className?: string
  chars?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)

  useGSAP(
    () => {
      const el = ref.current
      if (!el || !motionAllowed()) return
      gsap.to(el, {
        duration: Math.min(1.6, 0.5 + text.length * 0.03),
        scrambleText: { text, chars, revealDelay: 0.25, speed: 0.5 },
        ease: 'none',
        scrollTrigger: { trigger: el, start: 'top 95%', once: true },
      })
    },
    { scope: ref, dependencies: [text], revertOnUpdate: true },
  )

  return (
    <span ref={ref} className={cn('font-mono', className)}>
      {text}
    </span>
  )
}
