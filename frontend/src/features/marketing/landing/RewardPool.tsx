import { Draggable } from 'gsap/Draggable'
import { InertiaPlugin } from 'gsap/InertiaPlugin'
import { useRef, useState } from 'react'
import { Link } from 'react-router'

import { hasFinePointer, motionAllowed } from '@/hooks/useReducedMotion'
import type { BountySummary } from '@/lib/api/types'
import { CATEGORY_LABELS } from '@/lib/format'
import { gsap, useGSAP } from '@/lib/gsap'
import { formatAmount, formatAmountCompact, tryParseAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

gsap.registerPlugin(Draggable, InertiaPlugin)

const GRAVITY = 2600 // px/s², tuned so a thrown coin falls back across the hero in well under a second

type Circle = { x: number; y: number; r: number }

/** Reward in whole XLM as a number, only for sizing coins (display always uses the exact string). */
function rewardUnits(b: BountySummary): number {
  const stroops = tryParseAmount(b.reward_amount)
  return stroops === null ? 1 : Math.max(1, Number(stroops / 10_000_000n))
}

/** Stable pseudo-random order for a bounty id, so the floor looks the same on every visit. */
function hash(id: string): number {
  let h = 2166136261
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619)
  return h >>> 0
}

/**
 * Where a circle of radius `r` comes to rest if dropped at `x`: on the floor, or on the first circle it touches
 * on the way down.
 */
function restingY(x: number, r: number, others: Circle[], floor: number): number {
  let y = floor - r
  for (const c of others) {
    const dx = Math.abs(c.x - x)
    const reach = c.r + r
    if (dx < reach) y = Math.min(y, c.y - Math.sqrt(reach * reach - dx * dx))
  }
  return y
}

/**
 * Lays the coins along the floor: each gets an evenly spaced slot across the full width (in a stable shuffled
 * order), then settles at the lowest point near its slot. Radii shrink until the pile fits inside the floor band.
 */
function layFloor(
  ids: string[],
  units: number[],
  width: number,
  height: number,
  band: number,
): { circles: Circle[]; radii: number[] } {
  const min = Math.min(...units)
  const max = Math.max(...units)
  const t = (u: number) =>
    Math.log(max) - Math.log(min) < 0.01
      ? 0.5
      : (Math.log(u) - Math.log(min)) / (Math.log(max) - Math.log(min))
  const order = ids.map((id, i) => ({ i, h: hash(id) })).sort((a, b) => a.h - b.h)
  let rMin = Math.max(20, Math.min(46, band * 0.18))
  let rMax = Math.max(rMin + 8, Math.min(100, band * 0.36))
  for (let attempt = 0; attempt < 10; attempt++) {
    const radii = units.map((u) => Math.round(rMin + (rMax - rMin) * t(u)))
    const edge = Math.max(...radii)
    const placed: Circle[] = []
    const circles: Circle[] = new Array(ids.length)
    order.forEach(({ i }, slot) => {
      const r = radii[i]
      const target = edge + ((width - 2 * edge) * (slot + 0.5)) / ids.length
      let best = { x: target, y: -Infinity }
      for (let x = Math.max(r, target - r * 0.7); x <= Math.min(width - r, target + r * 0.7); x += 2) {
        const y = restingY(x, r, placed, height)
        if (y > best.y + 0.5) best = { x, y }
      }
      const circle = { x: best.x, y: best.y, r }
      placed.push(circle)
      circles[i] = circle
    })
    const top = Math.min(...circles.map((c) => c.y - c.r))
    if (top >= height - band || attempt === 9) return { circles, radii }
    rMin *= 0.9
    rMax *= 0.9
  }
  return { circles: [], radii: [] }
}

function Coin({ bounty }: { bounty: BountySummary }) {
  const funded = bounty.funding_status === 'FUNDED'
  const amount = formatAmountCompact(bounty.reward_amount)
  const exact = formatAmount(bounty.reward_amount, { maxDecimals: 2 })
  return (
    <Link
      to={`/bounties/${bounty.slug || bounty.id}`}
      data-reward-token
      draggable={false}
      aria-label={`${bounty.title}: ${exact} XLM reward, ${funded ? 'funded in escrow' : 'not funded yet'}`}
      className="group pointer-events-auto absolute top-0 left-0 rounded-full outline-none select-none hover:z-30 focus-visible:z-30 focus-visible:ring-4 focus-visible:ring-ring/60"
    >
      {/* Nudged away from the cursor by the pool. */}
      <span data-nudge className="block size-full">
        <span
          className={cn(
            'flex size-full flex-col items-center justify-center rounded-full leading-none transition-transform duration-300 ease-out group-hover:scale-[1.07] group-focus-visible:scale-[1.07]',
            funded
              ? 'bg-success text-success-foreground shadow-[inset_0_0_0_5px_rgb(255_255_255/0.14),0_14px_28px_-14px_rgb(19_122_70/0.75)]'
              : 'border border-input bg-card bg-[radial-gradient(circle,transparent_62%,var(--border)_63%,var(--border)_64%,transparent_65%)] text-foreground shadow-[inset_0_-6px_0_rgb(16_24_40/0.035),0_14px_28px_-16px_rgb(16_24_40/0.4)] dark:shadow-[0_14px_28px_-16px_rgb(0_0_0/0.8)]',
          )}
        >
          <span className="amount" style={{ fontSize: 'calc(var(--r) * 0.46)' }}>
            {amount}
          </span>
          <span
            className={cn(
              'mt-[0.2em] font-medium',
              funded ? 'text-success-foreground/90' : 'text-muted-foreground',
            )}
            style={{ fontSize: 'calc(var(--r) * 0.2)' }}
          >
            XLM
          </span>
        </span>
      </span>
      {/* What the coin is, on hover or focus. The link's accessible name already says this. */}
      <span
        aria-hidden
        className="pointer-events-none absolute bottom-full left-1/2 mb-3 w-60 -translate-x-1/2 translate-y-1 rounded-xl border bg-popover p-3 text-left text-popover-foreground opacity-0 shadow-lift transition-[opacity,translate] duration-200 group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100 group-data-[edge=end]:right-0 group-data-[edge=end]:left-auto group-data-[edge=end]:translate-x-0 group-data-[edge=start]:left-0 group-data-[edge=start]:translate-x-0"
      >
        <span className="line-clamp-2 text-sm leading-snug font-medium">{bounty.title}</span>
        <span className="mt-1.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{CATEGORY_LABELS[bounty.category]}</span>
          <span className={funded ? 'text-success' : undefined}>
            {funded ? 'Funded in escrow' : 'Not funded yet'}
          </span>
        </span>
      </span>
    </Link>
  )
}

/**
 * The hero's floor of open rewards: one coin per open bounty, sized by reward, green when the reward is locked in
 * escrow. The pool covers the whole hero (pointer events pass through to the text) and the coins rest in a band
 * along its bottom. They surface onto the floor on load; with a mouse you can pick them up and throw them anywhere
 * in the hero (Draggable + Inertia), they fall back onto the pile, and they lean away from the cursor.
 */
export function RewardPool({ bounties, band }: { bounties: BountySummary[]; band: number }) {
  const pool = useRef<HTMLDivElement>(null)
  const [interactive] = useState(() => motionAllowed() && hasFinePointer())
  const key = bounties.map((b) => b.id).join(',')

  useGSAP(
    () => {
      const el = pool.current
      if (!el || bounties.length === 0) return
      const tokens = Array.from(el.querySelectorAll<HTMLElement>('[data-reward-token]'))
      const ids = bounties.map((b) => b.id)
      const units = bounties.map(rewardUnits)
      const animate = motionAllowed()

      let circles: Circle[] = []
      const measure = () => {
        const { width, height } = el.getBoundingClientRect()
        const laid = layFloor(ids, units, width, height - 2, band)
        circles = laid.circles
        tokens.forEach((t, i) => {
          const r = laid.radii[i]
          t.style.width = t.style.height = `${r * 2}px`
          t.style.setProperty('--r', `${r}px`)
          // Hover cards near the edges open inwards instead of being clipped.
          t.dataset.edge = circles[i].x < 130 ? 'start' : circles[i].x > width - 130 ? 'end' : 'middle'
        })
        return height
      }
      const height = measure()
      const place = (i: number) =>
        gsap.set(tokens[i], { x: circles[i].x - circles[i].r, y: circles[i].y - circles[i].r })

      let entrance: gsap.core.Timeline | null = null
      if (!animate) {
        tokens.forEach((_, i) => place(i))
      } else {
        // Entrance: the coins surface onto the floor in a wave from the middle of the hero outwards, the coins on
        // the floor before the ones resting on top of them.
        const { width } = el.getBoundingClientRect()
        const rank: number[] = []
        circles
          .map((c, i) => ({ i, d: Math.abs(c.x - width / 2) / width + (height - c.y - c.r) / height }))
          .sort((a, b) => a.d - b.d)
          .forEach(({ i }, n) => (rank[i] = n))
        const tl = (entrance = gsap.timeline({ delay: 0.35 }))
        tokens.forEach((t, i) => {
          const c = circles[i]
          tl.fromTo(
            t,
            { x: c.x - c.r, y: c.y - c.r + Math.min(56, c.r * 0.9), autoAlpha: 0, scale: 0.9 },
            { y: c.y - c.r, autoAlpha: 1, scale: 1, duration: 1.1, ease: 'expo.out' },
            rank[i] * 0.06,
          )
        })
      }

      // Current centres of every coin except `skip` (coins may have been moved by hand).
      const current = (skip: number): Circle[] =>
        tokens.flatMap((t, i) =>
          i === skip
            ? []
            : [
                {
                  x: (gsap.getProperty(t, 'x') as number) + circles[i].r,
                  y: (gsap.getProperty(t, 'y') as number) + circles[i].r,
                  r: circles[i].r,
                },
              ],
        )

      /** Let a released coin fall onto whatever is below it. */
      const settle = (i: number) => {
        const t = tokens[i]
        const r = circles[i].r
        const cx = (gsap.getProperty(t, 'x') as number) + r
        const top = gsap.getProperty(t, 'y') as number
        const targetTop = restingY(cx, r, current(i), el.getBoundingClientRect().height - 2) - r
        if (targetTop <= top + 1) return
        const fall = Math.sqrt((2 * (targetTop - top)) / GRAVITY)
        gsap
          .timeline()
          .to(t, { y: targetTop, duration: fall, ease: 'power2.in' })
          .to(t, { y: targetTop - Math.min(12, r * 0.2), duration: 0.12, ease: 'power2.out' })
          .to(t, { y: targetTop, duration: 0.16, ease: 'power2.in' })
      }

      let recentlyDragged = false
      // Created once the entrance has finished: Draggable clamps its target into `bounds`, which would move coins
      // that are still rising from below the floor and throw off where they settle.
      const draggables: Draggable[] = []
      const enableDrag = () => {
        if (!interactive || draggables.length) return
        tokens.forEach((t, i) => {
          draggables.push(
            Draggable.create(t, {
              type: 'x,y',
              bounds: el,
              inertia: true,
              edgeResistance: 0.65,
              dragClickables: true,
              minimumMovement: 5,
              zIndexBoost: true,
              cursor: 'grab',
              activeCursor: 'grabbing',
              onPress: () => gsap.killTweensOf(t),
              onDragStart: () => {
                recentlyDragged = true
              },
              onRelease() {
                window.setTimeout(() => (recentlyDragged = false), 60)
                if (!this.isThrowing) settle(i)
              },
              onThrowComplete: () => settle(i),
            })[0],
          )
        })
      }
      if (entrance) entrance.eventCallback('onComplete', enableDrag)
      else enableDrag()

      // The click that ends a drag must not open the bounty.
      const onClickCapture = (e: MouseEvent) => {
        if (recentlyDragged) {
          e.preventDefault()
          e.stopPropagation()
        }
      }
      el.addEventListener('click', onClickCapture, true)

      // Coins lean away from the cursor and spring back when it leaves them.
      const host = el.parentElement ?? el
      const faces = tokens.map((t) => t.querySelector<HTMLElement>('[data-nudge]'))
      const nudged = new Set<number>()
      let frame = 0
      const onPointerMove = (e: PointerEvent) => {
        if (!interactive) return
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(() => {
          tokens.forEach((t, i) => {
            const face = faces[i]
            if (!face || t.matches(':active')) return
            const box = t.getBoundingClientRect()
            const dx = box.left + box.width / 2 - e.clientX
            const dy = box.top + box.height / 2 - e.clientY
            const reach = box.width / 2 + 90
            const d = Math.hypot(dx, dy)
            if (d < reach && d > 0) {
              const push = (1 - d / reach) * 16
              nudged.add(i)
              gsap.to(face, {
                x: (dx / d) * push,
                y: (dy / d) * push,
                duration: 0.4,
                ease: 'power3.out',
                overwrite: true,
              })
            } else if (nudged.has(i)) {
              nudged.delete(i)
              gsap.to(face, { x: 0, y: 0, duration: 0.9, ease: 'elastic.out(1, 0.35)', overwrite: true })
            }
          })
        })
      }
      const onPointerLeave = () => {
        nudged.forEach((i) => {
          const face = faces[i]
          if (face)
            gsap.to(face, { x: 0, y: 0, duration: 0.9, ease: 'elastic.out(1, 0.35)', overwrite: true })
        })
        nudged.clear()
      }
      host.addEventListener('pointermove', onPointerMove)
      host.addEventListener('pointerleave', onPointerLeave)

      // A resized hero re-lays the floor for the new size.
      let lastWidth = el.getBoundingClientRect().width
      const ro = new ResizeObserver(() => {
        const width = el.getBoundingClientRect().width
        if (Math.abs(width - lastWidth) < 4) return
        lastWidth = width
        measure()
        entrance?.kill()
        tokens.forEach((t, i) => {
          gsap.killTweensOf(t)
          gsap.set(t, { autoAlpha: 1, scale: 1 })
          place(i)
        })
        enableDrag()
        draggables.forEach((d) => d.applyBounds(el))
      })
      ro.observe(el)

      return () => {
        cancelAnimationFrame(frame)
        ro.disconnect()
        host.removeEventListener('pointermove', onPointerMove)
        host.removeEventListener('pointerleave', onPointerLeave)
        el.removeEventListener('click', onClickCapture, true)
        draggables.forEach((d) => d.kill())
      }
    },
    { scope: pool, dependencies: [key, interactive, band], revertOnUpdate: true },
  )

  return (
    <div
      ref={pool}
      role="group"
      aria-label="Open bounty rewards"
      className="pointer-events-none absolute inset-0 z-10"
    >
      {bounties.map((b) => (
        <Coin key={b.id} bounty={b} />
      ))}
    </div>
  )
}
