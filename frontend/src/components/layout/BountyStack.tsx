import { useRef } from 'react'

import { hasFinePointer, motionAllowed } from '@/hooks/useReducedMotion'
import { useFeaturedBounties } from '@/lib/api/queries/bounties'
import type { BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS } from '@/lib/format'
import { gsap, useGSAP } from '@/lib/gsap'
import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

/** Resting fan: each card's offset and tilt, back to front. */
const FAN = [
  { x: 36, y: 34, rotate: 5 },
  { x: 16, y: 16, rotate: 2 },
  { x: 0, y: 0, rotate: -2 },
] as const

function MiniCard({ bounty }: { bounty: BountySummary }) {
  const funded = bounty.funding_status === 'FUNDED'
  return (
    <div className="rounded-2xl border bg-card p-5 shadow-lift">
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>{CATEGORY_LABELS[bounty.category]}</span>
        <span
          className={cn(
            'rounded-[4px] px-1.5 py-0.5 font-medium',
            funded ? 'bg-success/10 text-success' : 'bg-muted text-muted-foreground',
          )}
        >
          {funded ? 'Funded in escrow' : 'Not funded yet'}
        </span>
      </div>
      <p className="mt-3 line-clamp-2 leading-snug font-medium">{bounty.title}</p>
      <p className="amount mt-4 text-[2rem] leading-none">
        {formatAmount(bounty.reward_amount, { maxDecimals: 2 })}
        <span className="ml-1.5 text-sm font-normal text-muted-foreground" style={{ fontStretch: '100%' }}>
          XLM
        </span>
      </p>
    </div>
  )
}

/**
 * Three real open bounties fanned out beside the sign-in form. They deal in when the page opens and lean towards
 * the pointer as it moves over the panel. Decorative: the marketplace is one click away for the real thing.
 */
export function BountyStack({ className }: { className?: string }) {
  const { data } = useFeaturedBounties()
  const root = useRef<HTMLDivElement>(null)
  const cards = (data ?? []).slice(0, 3).reverse()

  useGSAP(
    () => {
      const el = root.current
      if (!el) return
      const nodes = Array.from(el.querySelectorAll<HTMLElement>('[data-card]'))
      if (nodes.length === 0) return
      const fan = (i: number) => FAN[FAN.length - nodes.length + i]
      nodes.forEach((n, i) => gsap.set(n, { x: fan(i).x, y: fan(i).y, rotate: fan(i).rotate }))
      if (!motionAllowed()) return

      gsap.from(nodes, {
        y: 80,
        rotate: 0,
        autoAlpha: 0,
        duration: 0.9,
        stagger: 0.12,
        delay: 0.35,
        ease: 'bf-settle',
      })
      if (!hasFinePointer()) return

      // Pointer parallax: nearer cards move further, and the whole stack tilts towards the pointer.
      const host = el.closest('aside') ?? el
      const moves = nodes.map((n) => ({
        x: gsap.quickTo(n, 'x', { duration: 0.6, ease: 'power3.out' }),
        y: gsap.quickTo(n, 'y', { duration: 0.6, ease: 'power3.out' }),
        r: gsap.quickTo(n, 'rotate', { duration: 0.6, ease: 'power3.out' }),
      }))
      const onMove = (e: Event) => {
        const { clientX, clientY } = e as PointerEvent
        const box = host.getBoundingClientRect()
        const px = (clientX - box.left) / box.width - 0.5
        const py = (clientY - box.top) / box.height - 0.5
        moves.forEach((m, i) => {
          const depth = (i + 1) / nodes.length
          m.x(fan(i).x + px * 36 * depth)
          m.y(fan(i).y + py * 26 * depth)
          m.r(fan(i).rotate + px * 4 * depth)
        })
      }
      const onLeave = () =>
        moves.forEach((m, i) => {
          m.x(fan(i).x)
          m.y(fan(i).y)
          m.r(fan(i).rotate)
        })
      host.addEventListener('pointermove', onMove)
      host.addEventListener('pointerleave', onLeave)
      return () => {
        host.removeEventListener('pointermove', onMove)
        host.removeEventListener('pointerleave', onLeave)
      }
    },
    { scope: root, dependencies: [cards.map((b) => b.id).join()], revertOnUpdate: true },
  )

  if (cards.length === 0) return null
  return (
    <div ref={root} aria-hidden className={cn('relative grid pr-10 pb-10', className)}>
      {cards.map((b) => (
        <div key={b.id} data-card className="col-start-1 row-start-1 will-change-transform">
          <MiniCard bounty={b} />
        </div>
      ))}
    </div>
  )
}
