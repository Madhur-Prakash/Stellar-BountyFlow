import { ScrollSmoother } from 'gsap/ScrollSmoother'
import Lenis from 'lenis'
import { createContext, useContext, useEffect, type RefObject } from 'react'

import { gsap, ScrollTrigger } from '@/lib/gsap'
import { useScrollEngine } from '@/lib/scroll'

import { motionAllowed } from './useReducedMotion'

gsap.registerPlugin(ScrollSmoother)

/**
 * - `smoother`: GSAP ScrollSmoother. Needs the #smooth-wrapper / #smooth-content structure, enables `data-speed`
 *   and `data-lag` parallax. Used on the story pages, which have no sticky elements (they would break inside the
 *   transformed content).
 * - `lenis`: Lenis on the native window scroll, so `position: sticky`, dialogs and native scrollbars keep working.
 *   Used everywhere else.
 * Both are skipped under reduced motion.
 */
export type ScrollMode = 'smoother' | 'lenis'

// Elements that scroll on their own: wheel and touch over them must not move the page behind.
const OWN_SCROLL =
  '[role="dialog"], [role="alertdialog"], [role="listbox"], [role="menu"], [data-radix-popper-content-wrapper], [data-lenis-prevent], [cmdk-list]'

/** Refresh ScrollTrigger positions shortly after `el` changes height (queries resolving, images loading). */
function observeHeight(el: Element): () => void {
  let timer = 0
  let lastHeight = el.getBoundingClientRect().height
  const ro = new ResizeObserver(() => {
    const height = el.getBoundingClientRect().height
    if (Math.abs(height - lastHeight) < 2) return
    lastHeight = height
    window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      // Triggers are created as components mount, not in page order; refresh them top to bottom so each pin's
      // spacing is in place before the positions of the sections below it are measured.
      ScrollTrigger.sort()
      ScrollTrigger.refresh()
    }, 120)
  })
  ro.observe(el)
  return () => {
    ro.disconnect()
    window.clearTimeout(timer)
  }
}

function useLenisEngine(enabled: boolean) {
  useEffect(() => {
    if (!enabled || !motionAllowed()) return

    const lenis = new Lenis({
      autoRaf: false,
      lerp: 0.12,
      smoothWheel: true,
      allowNestedScroll: true,
      prevent: (node) => !!node.closest?.(OWN_SCROLL),
    })
    const onTick = (time: number) => lenis.raf(time * 1000)
    lenis.on('scroll', ScrollTrigger.update)
    gsap.ticker.add(onTick)
    gsap.ticker.lagSmoothing(0)

    // Radix marks <body data-scroll-locked> while a dialog, sheet or menu owns scrolling; pause Lenis meanwhile.
    const syncLock = () => (document.body.hasAttribute('data-scroll-locked') ? lenis.stop() : lenis.start())
    const lockObserver = new MutationObserver(syncLock)
    lockObserver.observe(document.body, { attributes: true, attributeFilter: ['data-scroll-locked'] })
    const stopObserving = observeHeight(document.body)

    useScrollEngine.getState().set({ lenis })
    return () => {
      stopObserving()
      lockObserver.disconnect()
      gsap.ticker.remove(onTick)
      gsap.ticker.lagSmoothing(500, 33)
      lenis.destroy()
      useScrollEngine.getState().set({ lenis: null })
    }
  }, [enabled])
}

function useSmootherEngine(
  enabled: boolean,
  wrapper: RefObject<HTMLElement | null> | undefined,
  content: RefObject<HTMLElement | null> | undefined,
  routeKey: string | undefined,
) {
  const smoother = useScrollEngine((s) => s.smoother)

  // One ScrollSmoother for as long as the layout is in smoother mode, so pins on every story page are created
  // against it (a pin created before ScrollSmoother, then rebuilt after it, leaves a nested pin spacer behind).
  useEffect(() => {
    if (!enabled || !motionAllowed()) return
    const wrapperEl = wrapper?.current
    const contentEl = content?.current
    if (!wrapperEl || !contentEl) return
    const instance = ScrollSmoother.create({
      wrapper: wrapperEl,
      content: contentEl,
      smooth: 1.1,
      effects: false,
      smoothTouch: false,
    })
    const stopObserving = observeHeight(contentEl)
    useScrollEngine.getState().set({ smoother: instance })
    return () => {
      stopObserving()
      instance.kill()
      useScrollEngine.getState().set({ smoother: null })
    }
  }, [enabled, wrapper, content])

  // Per page: start from the restored scroll position instead of gliding there from the previous page's, and
  // attach the new page's data-speed / data-lag parallax.
  useEffect(() => {
    const contentEl = content?.current
    if (!smoother || !contentEl) return
    smoother.scrollTo(window.scrollY, false)
    const effects = smoother.effects(contentEl.querySelectorAll('[data-speed], [data-lag]'))
    return () => effects.forEach((effect) => effect.kill())
  }, [smoother, content, routeKey])
}

/** Which engine a layout runs ('none' under reduced motion). Pinning components wait until it is active. */
export const ScrollModeContext = createContext<ScrollMode | 'none'>('none')

/** Mounts the smooth-scroll engine for a layout. Only one layout (and so one engine) is mounted at a time. */
export function useSmoothScroll(
  mode: ScrollMode,
  options: {
    wrapper?: RefObject<HTMLElement | null>
    content?: RefObject<HTMLElement | null>
    routeKey?: string
  } = {},
) {
  useLenisEngine(mode === 'lenis')
  useSmootherEngine(mode === 'smoother', options.wrapper, options.content, options.routeKey)
}

/** The active engine: 'smoother', 'lenis' or 'native'. */
export function useScrollEngineKey(): string {
  return useScrollEngine((s) => (s.smoother ? 'smoother' : s.lenis ? 'lenis' : 'native'))
}

/**
 * The active engine once it is the one the page's layout runs, `null` before that. Scroll-driven effects that pin
 * wait for a non-null value and list it as a dependency: a pin must be created against the engine it will live
 * with, or rebuilding it later leaves a nested pin spacer that breaks the layout below it.
 */
export function useScrollEngineReady(): string | null {
  const expected = useContext(ScrollModeContext)
  const engine = useScrollEngineKey()
  if (expected === 'none' || !motionAllowed()) return engine
  return engine === expected ? engine : null
}
