import { MessageSquareText } from 'lucide-react'
import { Suspense, lazy, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { useLocation } from 'react-router'

import { Button } from '@/components/ui/button'
import { useUiPrefs } from '@/stores/ui-prefs'

const FeedbackDialog = lazy(() => import('./FeedbackDialog'))

/** Space kept between the button and whatever it steps over. */
const GAP = 12
/** Resting distance from the bottom and right edges, outside any safe area. */
const INSET = 16
/** Smallest gap the button keeps from the window edge once it has been dragged. */
const EDGE = 12
/** Pointer travel that separates a drag from a click, so moving it never opens the dialog. */
const DRAG_THRESHOLD = 5
/** How far one Alt+Arrow press moves it, for anyone who cannot drag. */
const NUDGE = 24

type Point = { x: number; y: number }

/** Keeps a pixel position inside the window, leaving `EDGE` around it. */
function clampToViewport(left: number, top: number, w: number, h: number): Point {
  return {
    x: Math.min(Math.max(left, EDGE), Math.max(EDGE, window.innerWidth - w - EDGE)),
    y: Math.min(Math.max(top, EDGE), Math.max(EDGE, window.innerHeight - h - EDGE)),
  }
}

/** Pixels → the stored fraction of free space, so the spot survives a resize or a different screen. */
function toFraction(p: Point, w: number, h: number): Point {
  const spanX = Math.max(1, window.innerWidth - w - EDGE * 2)
  const spanY = Math.max(1, window.innerHeight - h - EDGE * 2)
  return {
    x: Math.min(1, Math.max(0, (p.x - EDGE) / spanX)),
    y: Math.min(1, Math.max(0, (p.y - EDGE) / spanY)),
  }
}

/**
 * How far the button has to lift to clear a page's primary action. Pages mark theirs with
 * `data-primary-action`: the bounty form's sticky bar and the landing page's closing actions. Overlap is
 * measured against the button's *resting* box, so lifting out of the way can never flip the answer back.
 */
function useClearance(ref: RefObject<HTMLElement | null>, pathname: string, enabled: boolean): number {
  const [lift, setLift] = useState(0)
  const applied = useRef(0)

  useEffect(() => {
    // Off once the viewer has parked the button themselves: nothing should move it but them.
    if (!enabled) return
    let frame = 0

    const measure = () => {
      frame = 0
      const el = ref.current
      if (!el) return
      const obstacles = document.querySelectorAll<HTMLElement>('[data-primary-action]')
      let next = 0
      if (obstacles.length > 0) {
        const box = el.getBoundingClientRect()
        const top = box.top + applied.current
        const bottom = box.bottom + applied.current
        for (const node of obstacles) {
          const r = node.getBoundingClientRect()
          if (r.width === 0 || r.height === 0) continue
          if (r.right <= box.left - GAP || r.left >= box.right + GAP) continue
          if (r.bottom <= top || r.top >= bottom) continue
          next = Math.max(next, Math.round(window.innerHeight - r.top + GAP))
        }
      }
      if (next !== applied.current) {
        applied.current = next
        setLift(next)
      }
    }

    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }

    schedule()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
    }
  }, [ref, pathname, enabled])

  return lift
}

/**
 * The floating feedback button: bottom right of the public site and the workspace (never on the auth screens
 * or in the admin console, which do not mount it). The dialog is a separate chunk, fetched on the first click,
 * and gets a fresh mount each time it opens so nobody reopens it onto their last message.
 */
export function FeedbackLauncher() {
  const { pathname } = useLocation()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const placed = useUiPrefs((s) => s.feedbackPos)
  const setPlaced = useUiPrefs((s) => s.setFeedbackPos)
  const resetPlaced = useUiPrefs((s) => s.resetFeedbackPos)
  // A button the viewer has parked themselves stays put: stepping it out of the way would move it
  // somewhere they did not choose.
  const measured = useClearance(buttonRef, pathname, !placed)
  const lift = placed ? 0 : measured
  const [open, setOpen] = useState(false)
  const [session, setSession] = useState(0)

  // Where the button actually sits, in pixels: resolved from the stored fraction, and live while dragging.
  const [spot, setSpot] = useState<Point | null>(null)
  const drag = useRef<{ id: number; dx: number; dy: number; moved: boolean } | null>(null)
  const latest = useRef<Point | null>(null)
  const wasDragged = useRef(false)

  useLayoutEffect(() => {
    const el = buttonRef.current
    if (!el || !placed) {
      setSpot(null)
      return
    }
    const apply = () => {
      const { width, height } = el.getBoundingClientRect()
      const spanX = Math.max(1, window.innerWidth - width - EDGE * 2)
      const spanY = Math.max(1, window.innerHeight - height - EDGE * 2)
      setSpot(clampToViewport(EDGE + placed.x * spanX, EDGE + placed.y * spanY, width, height))
    }
    apply()
    window.addEventListener('resize', apply)
    return () => window.removeEventListener('resize', apply)
  }, [placed])

  const move = (left: number, top: number) => {
    const el = buttonRef.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const next = clampToViewport(left, top, width, height)
    latest.current = next
    setSpot(next)
  }

  const commit = () => {
    const el = buttonRef.current
    if (!el || !latest.current) return
    const { width, height } = el.getBoundingClientRect()
    setPlaced(toFraction(latest.current, width, height))
  }

  return (
    <>
      <Button
        ref={buttonRef}
        type="button"
        variant="outline"
        onClick={() => {
          // The click that ends a drag is not a request to open anything.
          if (wasDragged.current) {
            wasDragged.current = false
            return
          }
          setSession((n) => n + 1)
          setOpen(true)
        }}
        onPointerDown={(e) => {
          if (e.pointerType === 'mouse' && e.button !== 0) return
          const box = e.currentTarget.getBoundingClientRect()
          drag.current = { id: e.pointerId, dx: e.clientX - box.left, dy: e.clientY - box.top, moved: false }
          latest.current = { x: box.left, y: box.top }
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={(e) => {
          const d = drag.current
          if (!d || d.id !== e.pointerId) return
          const left = e.clientX - d.dx
          const top = e.clientY - d.dy
          if (!d.moved) {
            const from = latest.current
            if (!from) return
            if (Math.abs(left - from.x) < DRAG_THRESHOLD && Math.abs(top - from.y) < DRAG_THRESHOLD) return
            d.moved = true
          }
          move(left, top)
        }}
        onPointerUp={(e) => {
          const d = drag.current
          if (!d || d.id !== e.pointerId) return
          drag.current = null
          e.currentTarget.releasePointerCapture?.(e.pointerId)
          if (!d.moved) return
          wasDragged.current = true
          commit()
        }}
        onPointerCancel={() => {
          drag.current = null
        }}
        onKeyDown={(e) => {
          // Dragging is a pointer gesture, so the same move is available from the keyboard.
          if (!e.altKey) return
          if (e.key === '0') {
            e.preventDefault()
            resetPlaced()
            return
          }
          const step: Record<string, [number, number]> = {
            ArrowLeft: [-NUDGE, 0],
            ArrowRight: [NUDGE, 0],
            ArrowUp: [0, -NUDGE],
            ArrowDown: [0, NUDGE],
          }
          const delta = step[e.key]
          if (!delta) return
          e.preventDefault()
          const box = e.currentTarget.getBoundingClientRect()
          move(box.left + delta[0], box.top + delta[1])
          commit()
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Drag to move. Alt with the arrow keys moves it too, and Alt+0 puts it back."
        className="fixed z-40 touch-none rounded-full bg-card px-4 shadow-lift select-none max-sm:gap-0 max-sm:px-3"
        style={
          spot
            ? { left: `${spot.x}px`, top: `${spot.y}px` }
            : {
                bottom: `calc(env(safe-area-inset-bottom, 0px) + ${INSET + lift}px)`,
                right: `calc(env(safe-area-inset-right, 0px) + ${INSET}px)`,
              }
        }
      >
        <MessageSquareText aria-hidden />
        {/* Below sm the label is read but not drawn, so the button stays a small disc on a phone. */}
        <span className="max-sm:sr-only">Feedback</span>
      </Button>

      {session > 0 && (
        <Suspense fallback={null}>
          {/* The dialog mounts a tick after the click, by which point Radix can no longer tell which
              element opened it, so closing returns focus to the button here rather than relying on that. */}
          <FeedbackDialog
            key={session}
            open={open}
            onOpenChange={(next) => {
              setOpen(next)
              if (!next) buttonRef.current?.focus()
            }}
          />
        </Suspense>
      )}
    </>
  )
}
