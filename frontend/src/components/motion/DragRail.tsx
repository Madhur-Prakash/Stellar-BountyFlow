import { Draggable } from 'gsap/Draggable'
import { InertiaPlugin } from 'gsap/InertiaPlugin'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Children, useRef, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { hasFinePointer, motionAllowed } from '@/hooks/useReducedMotion'
import { gsap, useGSAP } from '@/lib/gsap'
import { cn } from '@/lib/utils'

gsap.registerPlugin(Draggable, InertiaPlugin)

/**
 * A horizontal rail of cards. With a mouse or trackpad you grab it and throw it: it glides with inertia and comes
 * to rest on a card edge. Touch devices and reduced motion get native horizontal scrolling with snap points.
 * Previous / next buttons and keyboard focus work in both modes.
 */
export function DragRail({
  children,
  label,
  className,
  itemClassName,
}: {
  children: ReactNode
  label: string
  className?: string
  itemClassName?: string
}) {
  const root = useRef<HTMLDivElement>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const track = useRef<HTMLUListElement>(null)
  const bar = useRef<HTMLSpanElement>(null)
  const controller = useRef<{ step: (dir: 1 | -1) => void } | null>(null)
  const [interactive] = useState(() => motionAllowed() && hasFinePointer())
  const [edges, setEdges] = useState({ start: true, end: false })
  const items = Children.toArray(children)

  useGSAP(
    () => {
      const vp = viewport.current
      const tr = track.current
      if (!vp || !tr) return

      const maxScroll = () => Math.max(0, tr.scrollWidth - vp.clientWidth)
      const offsets = () => Array.from(tr.children, (li) => -(li as HTMLElement).offsetLeft)
      let lastEdges = ''
      const report = (position: number) => {
        const max = maxScroll()
        const progress = max === 0 ? 1 : Math.min(1, Math.max(0, -position / max))
        if (bar.current) gsap.set(bar.current, { scaleX: Math.max(0.08, progress) })
        const start = progress <= 0.001
        const end = progress >= 0.999
        // Only re-render when a button's enabled state actually changes, not on every drag frame.
        if (`${start}${end}` !== lastEdges) {
          lastEdges = `${start}${end}`
          setEdges({ start, end })
        }
      }

      if (!interactive) {
        // Native scrolling: the buttons scroll by roughly one viewport, snapping does the rest.
        const onScroll = () => report(-vp.scrollLeft)
        vp.addEventListener('scroll', onScroll, { passive: true })
        report(0)
        controller.current = {
          step: (dir) =>
            vp.scrollBy({ left: dir * vp.clientWidth * 0.85, behavior: motionAllowed() ? 'smooth' : 'auto' }),
        }
        return () => vp.removeEventListener('scroll', onScroll)
      }

      const snapTo = (x: number) => {
        const max = maxScroll()
        const clamped = Math.min(0, Math.max(-max, x))
        const stops = offsets().filter((o) => o >= -max)
        if (!stops.includes(-max)) stops.push(-max)
        return stops.reduce((best, o) => (Math.abs(o - clamped) < Math.abs(best - clamped) ? o : best), 0)
      }

      let recentlyDragged = false
      const [drag] = Draggable.create(tr, {
        type: 'x',
        bounds: vp,
        inertia: true,
        edgeResistance: 0.82,
        dragClickables: true,
        minimumMovement: 6,
        cursor: 'grab',
        activeCursor: 'grabbing',
        snap: { x: snapTo },
        // Grabbing the rail mid-glide (after a button press) takes over from that animation.
        onPress: () => {
          gsap.killTweensOf(tr)
        },
        onDragStart: () => {
          recentlyDragged = true
        },
        onDrag() {
          report(this.x)
        },
        onThrowUpdate() {
          report(this.x)
        },
        onRelease() {
          // Let the click that ends a drag be swallowed below, then allow normal clicks again.
          window.setTimeout(() => (recentlyDragged = false), 60)
        },
      })

      // A drag that ends over a card must not also open it.
      const onClickCapture = (e: MouseEvent) => {
        if (recentlyDragged) {
          e.preventDefault()
          e.stopPropagation()
        }
      }
      vp.addEventListener('click', onClickCapture, true)

      const moveTo = (x: number) =>
        gsap.to(tr, {
          x: snapTo(x),
          duration: 0.7,
          ease: 'bf-settle',
          overwrite: true,
          onUpdate: () => {
            drag.update()
            report(gsap.getProperty(tr, 'x') as number)
          },
        })

      controller.current = {
        step: (dir) => moveTo((gsap.getProperty(tr, 'x') as number) - dir * vp.clientWidth * 0.85),
      }

      // Keyboard focus moving onto a card that is out of view brings it into view.
      const onFocusIn = (e: FocusEvent) => {
        const li = (e.target as HTMLElement).closest('li')
        if (!li || li.parentElement !== tr) return
        const x = gsap.getProperty(tr, 'x') as number
        const left = li.offsetLeft + x
        const right = left + li.offsetWidth
        vp.scrollLeft = 0 // the browser may scroll the clipped viewport itself; undo that
        if (left < 0 || right > vp.clientWidth) moveTo(-li.offsetLeft)
      }
      tr.addEventListener('focusin', onFocusIn)

      const onResize = () => {
        drag.applyBounds(vp)
        const x = gsap.getProperty(tr, 'x') as number
        gsap.set(tr, { x: Math.max(-maxScroll(), Math.min(0, x)) })
        drag.update()
        report(gsap.getProperty(tr, 'x') as number)
      }
      const ro = new ResizeObserver(onResize)
      ro.observe(vp)
      report(0)

      return () => {
        ro.disconnect()
        vp.removeEventListener('click', onClickCapture, true)
        tr.removeEventListener('focusin', onFocusIn)
        drag.kill()
      }
    },
    { scope: root, dependencies: [items.length, interactive], revertOnUpdate: true },
  )

  return (
    <div ref={root} className={cn('relative', className)}>
      <div
        ref={viewport}
        role="region"
        aria-label={`${label} list`}
        className={cn(
          'mask-[linear-gradient(to_right,transparent,black_12px,black_calc(100%-56px),transparent)]',
          interactive
            ? 'overflow-hidden'
            : 'snap-x snap-mandatory [scrollbar-width:none] overflow-x-auto overscroll-x-contain [&::-webkit-scrollbar]:hidden',
        )}
      >
        <ul ref={track} className="flex w-max gap-4 pr-14 pb-1 will-change-transform">
          {items.map((child, i) => (
            <li key={i} className={cn('shrink-0 snap-start', itemClassName)}>
              {child}
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-5 flex items-center gap-4">
        <div className="relative h-px flex-1 bg-border" aria-hidden>
          <span
            ref={bar}
            className="absolute inset-y-0 left-0 w-full origin-left scale-x-[0.08] bg-foreground"
          />
        </div>
        <div className="flex gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={`Previous ${label.toLowerCase()}`}
            disabled={edges.start}
            onClick={() => controller.current?.step(-1)}
          >
            <ChevronLeft />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={`Next ${label.toLowerCase()}`}
            disabled={edges.end}
            onClick={() => controller.current?.step(1)}
          >
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  )
}
