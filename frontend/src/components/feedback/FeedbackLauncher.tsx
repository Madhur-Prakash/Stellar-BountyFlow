import { Eye, MessageSquareText, Move, RotateCcw, Type } from 'lucide-react'
import { Suspense, lazy, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { useLocation } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { useUiPrefs, type FeedbackSize, type FeedbackStyle } from '@/stores/ui-prefs'

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

const SIZE_CLASS: Record<FeedbackSize, { pill: string; disc: string; icon: string }> = {
  sm: { pill: 'h-8 gap-1.5 px-3 text-[0.8125rem]', disc: 'size-9', icon: 'size-4' },
  md: { pill: 'h-10 gap-2 px-4 text-sm', disc: 'size-11', icon: 'size-4.5' },
  lg: { pill: 'h-12 gap-2.5 px-5 text-base', disc: 'size-14', icon: 'size-5.5' },
}

const STYLE_CLASS: Record<FeedbackStyle, string> = {
  outline: 'border bg-card text-foreground hover:bg-muted',
  solid: 'border-transparent bg-primary text-primary-foreground hover:bg-primary/90',
  subtle:
    'border-transparent bg-card/75 text-muted-foreground backdrop-blur hover:bg-card hover:text-foreground',
}

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
 *
 * It is the viewer's to arrange. Drag it anywhere, or right-click it (or press the menu key) for size, shape,
 * weight, edge-snapping and hiding. Everything is kept per browser in `ui-prefs`.
 */
export function FeedbackLauncher() {
  const { pathname } = useLocation()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const placed = useUiPrefs((s) => s.feedbackPos)
  const setPlaced = useUiPrefs((s) => s.setFeedbackPos)
  const cfg = useUiPrefs((s) => s.feedbackButton)
  const setCfg = useUiPrefs((s) => s.setFeedbackButton)
  const resetAll = useUiPrefs((s) => s.resetFeedbackButton)

  // A button the viewer has parked themselves stays put: stepping it out of the way would move it
  // somewhere they did not choose.
  const measured = useClearance(buttonRef, pathname, !placed && !cfg.hidden)
  const lift = placed ? 0 : measured
  const [open, setOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [session, setSession] = useState(0)

  // Where the button actually sits, in pixels: resolved from the stored fraction, and live while dragging.
  const [spot, setSpot] = useState<Point | null>(null)
  const drag = useRef<{ id: number; dx: number; dy: number; moved: boolean } | null>(null)
  const latest = useRef<Point | null>(null)
  const wasDragged = useRef(false)

  // Hiding it cannot be a one-way door, so the same shortcut brings it back from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.key.toLowerCase() !== 'f') return
      e.preventDefault()
      const now = useUiPrefs.getState().feedbackButton.hidden
      useUiPrefs.getState().setFeedbackButton({ hidden: !now })
      if (now) window.setTimeout(() => buttonRef.current?.focus(), 0)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

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
  }, [placed, cfg.size, cfg.showLabel])

  if (cfg.hidden) return null

  const size = SIZE_CLASS[cfg.size]

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
    let point = latest.current
    if (cfg.snap) {
      // Snap sideways only: vertical position is usually the deliberate part of the choice.
      const toLeft = point.x
      const toRight = window.innerWidth - (point.x + width)
      point = { x: toLeft <= toRight ? EDGE : window.innerWidth - width - EDGE, y: point.y }
      latest.current = point
      setSpot(point)
    }
    setPlaced(toFraction(point, width, height))
  }

  return (
    <>
      <div
        className="fixed z-40"
        style={
          spot
            ? { left: `${spot.x}px`, top: `${spot.y}px` }
            : {
                bottom: `calc(env(safe-area-inset-bottom, 0px) + ${INSET + lift}px)`,
                right: `calc(env(safe-area-inset-right, 0px) + ${INSET}px)`,
              }
        }
      >
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          {/* Anchors the menu to the button without making a left-click open it. */}
          <DropdownMenuTrigger asChild>
            <span aria-hidden className="pointer-events-none absolute inset-0" />
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="end" className="w-60">
            <DropdownMenuLabel>Feedback button</DropdownMenuLabel>
            <DropdownMenuSeparator />

            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Size</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={cfg.size}
              onValueChange={(v) => setCfg({ size: v as FeedbackSize })}
            >
              <DropdownMenuRadioItem value="sm">Small</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="md">Medium</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="lg">Large</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />

            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
              Weight
            </DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={cfg.style}
              onValueChange={(v) => setCfg({ style: v as FeedbackStyle })}
            >
              <DropdownMenuRadioItem value="outline">Outlined</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="solid">Solid</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="subtle">Quiet</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />

            <DropdownMenuCheckboxItem
              checked={cfg.showLabel}
              onCheckedChange={(v) => setCfg({ showLabel: v })}
            >
              <Type aria-hidden /> Show the word
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={cfg.snap} onCheckedChange={(v) => setCfg({ snap: v })}>
              <Move aria-hidden /> Snap to the side
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />

            <DropdownMenuItem
              onSelect={() => {
                setCfg({ hidden: true })
                toast('Feedback button hidden', { description: 'Alt+F brings it back.' })
              }}
            >
              <Eye aria-hidden /> Hide it
              <DropdownMenuShortcut>Alt+F</DropdownMenuShortcut>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => resetAll()}>
              <RotateCcw aria-hidden /> Put it back
              <DropdownMenuShortcut>Alt+0</DropdownMenuShortcut>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

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
          onContextMenu={(e) => {
            // Right-click, long-press and the keyboard menu key all arrive here.
            e.preventDefault()
            setMenuOpen(true)
          }}
          onPointerDown={(e) => {
            if (e.pointerType === 'mouse' && e.button !== 0) return
            // Cleared per press: a drag that ends off the button fires no click, and a stale flag here
            // would swallow the next real one.
            wasDragged.current = false
            const box = e.currentTarget.getBoundingClientRect()
            drag.current = {
              id: e.pointerId,
              dx: e.clientX - box.left,
              dy: e.clientY - box.top,
              moved: false,
            }
            latest.current = { x: box.left, y: box.top }
            // Guarded: pointer capture keeps the drag alive outside the button, but jsdom has no such method.
            e.currentTarget.setPointerCapture?.(e.pointerId)
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
            // Dragging is a pointer gesture, so the same moves are available from the keyboard.
            if (!e.altKey) return
            if (e.key === '0') {
              e.preventDefault()
              resetAll()
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
          title="Drag to move. Right-click to change it. Alt+F hides it."
          className={cn(
            'touch-none rounded-full shadow-lift select-none',
            STYLE_CLASS[cfg.style],
            cfg.showLabel ? size.pill : cn(size.disc, 'p-0'),
            `[&_svg:not([class*='size-'])]:${size.icon}`,
          )}
        >
          <MessageSquareText aria-hidden className={size.icon} />
          <span className={cn(!cfg.showLabel && 'sr-only')}>Feedback</span>
        </Button>
      </div>

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
