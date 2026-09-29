import { MessageSquareText } from 'lucide-react'
import { Suspense, lazy, useEffect, useRef, useState, type RefObject } from 'react'
import { useLocation } from 'react-router'

import { Button } from '@/components/ui/button'

const FeedbackDialog = lazy(() => import('./FeedbackDialog'))

/** Space kept between the button and whatever it steps over. */
const GAP = 12
/** Resting distance from the bottom and right edges, outside any safe area. */
const INSET = 16

/**
 * How far the button has to lift to clear a page's primary action. Pages mark theirs with
 * `data-primary-action`: the bounty form's sticky bar and the landing page's closing actions. Overlap is
 * measured against the button's *resting* box, so lifting out of the way can never flip the answer back.
 */
function useClearance(ref: RefObject<HTMLElement | null>, pathname: string): number {
  const [lift, setLift] = useState(0)
  const applied = useRef(0)

  useEffect(() => {
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
  }, [ref, pathname])

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
  const lift = useClearance(buttonRef, pathname)
  const [open, setOpen] = useState(false)
  const [session, setSession] = useState(0)

  return (
    <>
      <Button
        ref={buttonRef}
        type="button"
        variant="outline"
        onClick={() => {
          setSession((n) => n + 1)
          setOpen(true)
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="fixed z-40 rounded-full bg-card px-4 shadow-lift max-sm:gap-0 max-sm:px-3"
        style={{
          bottom: `calc(env(safe-area-inset-bottom, 0px) + ${INSET + lift}px)`,
          right: `calc(env(safe-area-inset-right, 0px) + ${INSET}px)`,
        }}
      >
        <MessageSquareText aria-hidden />
        {/* Below sm the label is read but not drawn, so the button stays a small disc on a phone. */}
        <span className="max-sm:sr-only">Feedback</span>
      </Button>

      {session > 0 && (
        <Suspense fallback={null}>
          <FeedbackDialog key={session} open={open} onOpenChange={setOpen} />
        </Suspense>
      )}
    </>
  )
}
