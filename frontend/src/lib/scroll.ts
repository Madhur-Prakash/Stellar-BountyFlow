import type Lenis from 'lenis'
import { create } from 'zustand'

import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap } from '@/lib/gsap'

/**
 * The page's smooth-scroll engine: Lenis on the public site, none in the workspace or under reduced motion.
 * See useSmoothScroll.
 */
type ScrollEngine = {
  lenis: Lenis | null
  set: (engine: Partial<Pick<ScrollEngine, 'lenis'>>) => void
}

export const useScrollEngine = create<ScrollEngine>()((set) => ({
  lenis: null,
  set: (engine) => set(engine),
}))

/** Height of the sticky site header plus breathing room: anchor targets land below it. */
export const HEADER_OFFSET = 80

/** Scroll so `el` sits just below the header, through whichever engine is active. */
export function scrollToElement(el: Element, { offset = HEADER_OFFSET, immediate = false } = {}) {
  const { lenis } = useScrollEngine.getState()
  if (lenis) {
    // Lenis caches the scroll limit; content that loaded since the last resize would clamp the target.
    lenis.resize()
    lenis.scrollTo(el as HTMLElement, { offset: -offset, immediate, duration: 1.1 })
    return
  }
  if (!immediate && motionAllowed()) {
    gsap.to(window, {
      duration: 0.9,
      ease: 'power2.inOut',
      scrollTo: { y: el, offsetY: offset, autoKill: true },
    })
  } else {
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset })
  }
}

/** Jump to the top of the page (e.g. after changing a results page), keeping the smooth-scroll engine in sync. */
export function scrollToTop() {
  const { lenis } = useScrollEngine.getState()
  if (lenis) lenis.scrollTo(0, { immediate: true })
  else window.scrollTo({ top: 0 })
}

/** Scroll the page to an absolute position through the active engine. */
export function scrollToY(y: number) {
  const { lenis } = useScrollEngine.getState()
  if (lenis) lenis.scrollTo(y, { duration: 1 })
  else if (motionAllowed())
    gsap.to(window, { duration: 0.9, ease: 'power2.inOut', scrollTo: { y, autoKill: true } })
  else window.scrollTo({ top: y })
}

/** Smooth-scroll to `#id` and move focus there (without a second jump) for keyboard and screen-reader users. */
export function scrollToAnchor(hash: string) {
  const id = decodeURIComponent(hash.replace(/^#/, ''))
  if (!id) return
  const el = document.getElementById(id)
  if (!el) return
  scrollToElement(el)
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: true })
}

/** True while any loading placeholder (shadcn skeleton or a boneyard overlay) is still on the page. */
function pageIsLoading(): boolean {
  return !!document.querySelector('main [data-slot="skeleton"], main [data-boneyard-overlay]')
}

/**
 * Scrolls to `#id` once the target exists and the page above it has settled (lazy route loaded, skeletons
 * replaced, position stable for a few frames). Used when arriving at "/#section" from another page.
 * Returns a cancel function.
 */
export function scrollToAnchorWhenReady(hash: string, timeoutMs = 4000): () => void {
  const id = decodeURIComponent(hash.replace(/^#/, ''))
  if (!id) return () => {}
  const deadline = performance.now() + timeoutMs
  let raf = 0
  let lastTop: number | null = null
  let stableFrames = 0
  const tick = () => {
    const el = document.getElementById(id)
    if (el) {
      const top = el.getBoundingClientRect().top + window.scrollY
      stableFrames = lastTop !== null && Math.abs(top - lastTop) < 1 ? stableFrames + 1 : 0
      lastTop = top
      if (!pageIsLoading() && stableFrames >= 6) {
        scrollToAnchor(`#${id}`)
        return
      }
    }
    if (performance.now() < deadline) raf = requestAnimationFrame(tick)
    else if (el) scrollToAnchor(`#${id}`)
  }
  raf = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(raf)
}
