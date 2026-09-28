import { flushSync } from 'react-dom'

import { motionAllowed } from '@/hooks/useReducedMotion'
import { useUiPrefs, type Theme } from '@/stores/ui-prefs'

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => { ready: Promise<void>; finished: Promise<void> }
}

/**
 * Switches the theme with a transition: the new theme grows as a circle from where the switch was pressed (View
 * Transitions API). Browsers without it get a short colour crossfade; reduced motion switches instantly.
 */
export function switchTheme(next: Theme, origin?: { x: number; y: number }) {
  const apply = () => flushSync(() => useUiPrefs.getState().setTheme(next))
  const root = document.documentElement
  if (!motionAllowed()) {
    apply()
    return
  }

  const doc = document as ViewTransitionDocument
  if (!doc.startViewTransition) {
    root.classList.add('theme-fading')
    apply()
    window.setTimeout(() => root.classList.remove('theme-fading'), 450)
    return
  }

  const x = origin?.x ?? window.innerWidth - 48
  const y = origin?.y ?? 32
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))
  const transition = doc.startViewTransition(apply)
  transition.ready
    .then(() => {
      root.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        {
          duration: 700,
          easing: 'cubic-bezier(0.22, 0.8, 0.2, 1)',
          pseudoElement: '::view-transition-new(root)',
        },
      )
    })
    .catch(() => {
      // The transition was skipped (e.g. the page was hidden); the theme has already been applied.
    })
}

/** The centre of the element that triggered a theme switch, as the origin of the reveal. */
export function originOf(el: Element | null | undefined): { x: number; y: number } | undefined {
  if (!el) return undefined
  const r = el.getBoundingClientRect()
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
}
