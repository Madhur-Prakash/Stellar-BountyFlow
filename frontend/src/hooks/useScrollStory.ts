import type { gsap as Gsap } from 'gsap'
import type { ScrollTrigger as ScrollTriggerStatic } from 'gsap/ScrollTrigger'
import { useEffect, type RefObject } from 'react'

import { useMediaQuery } from './useMediaQuery'
import { motionAllowed, useReducedMotion } from './useReducedMotion'

export type ScrollStoryTools = { gsap: typeof Gsap; ScrollTrigger: typeof ScrollTriggerStatic }

let tools: Promise<ScrollStoryTools> | null = null

/** GSAP with ScrollTrigger and DrawSVG, loaded on first use so pages without a scroll story never download it. */
export function loadScrollStoryTools(): Promise<ScrollStoryTools> {
  tools ??= Promise.all([import('gsap'), import('gsap/ScrollTrigger'), import('gsap/DrawSVGPlugin')]).then(
    ([{ gsap }, { ScrollTrigger }, { DrawSVGPlugin }]) => {
      gsap.registerPlugin(ScrollTrigger, DrawSVGPlugin)
      ScrollTrigger.config({ ignoreMobileResize: true })
      return { gsap, ScrollTrigger }
    },
  )
  return tools
}

/** Whether a section tells its story on scroll: motion allowed and a wide enough screen. */
export function useScrollStoryEnabled(minWidth: string): boolean {
  const wide = useMediaQuery(`(min-width: ${minWidth})`)
  const reduced = useReducedMotion()
  return wide && !reduced && motionAllowed()
}

/**
 * The scroll story's stage sticks this far below the top of the window (just under the 64px site header).
 * Stories use `STORY_STAGE_TOP` for the sticky offset so the timeline and the layout agree.
 */
export const STORY_STAGE_TOP = 80

/**
 * Scrubs a GSAP timeline across a wrapper whose first child is a `position: sticky` stage (top: `top` px) and
 * whose bottom padding is the scroll distance. CSS keeps the stage in view (no pin spacers). The story runs from
 * the moment the stage sticks to the moment it lets go, so it ends exactly where the stage's content ends and
 * scrolling back plays it in reverse. `build` creates the tweens and returns the timeline; `onProgress` receives
 * 0–1 for anything React renders (step counters, active states). Positions are re-measured whenever the page
 * height changes, because content above loads after this mounts.
 */
export function useScrollStory(
  wrapper: RefObject<HTMLElement | null>,
  enabled: boolean,
  build: (tools: ScrollStoryTools, root: HTMLElement) => gsap.core.Timeline,
  onProgress?: (progress: number) => void,
  top = STORY_STAGE_TOP,
) {
  useEffect(() => {
    const root = wrapper.current
    if (!enabled || !root) return
    let alive = true
    let cleanup: (() => void) | undefined
    void loadScrollStoryTools().then(({ gsap, ScrollTrigger }) => {
      if (!alive) return
      const ctx = gsap.context(() => {
        const timeline = build({ gsap, ScrollTrigger }, root)
        const stage = root.firstElementChild as HTMLElement | null
        ScrollTrigger.create({
          trigger: root,
          start: `top top+=${top}`,
          end: () => `+=${Math.max(1, root.offsetHeight - (stage?.offsetHeight ?? 0))}`,
          scrub: 0.6,
          animation: timeline,
          invalidateOnRefresh: true,
          onUpdate: (self) => onProgress?.(self.progress),
        })
      }, root)

      let timer = 0
      let lastHeight = document.body.scrollHeight
      const ro = new ResizeObserver(() => {
        const height = document.body.scrollHeight
        if (Math.abs(height - lastHeight) < 2) return
        lastHeight = height
        window.clearTimeout(timer)
        timer = window.setTimeout(() => ScrollTrigger.refresh(), 150)
      })
      ro.observe(document.body)
      cleanup = () => {
        window.clearTimeout(timer)
        ro.disconnect()
        ctx.revert()
      }
    })
    return () => {
      alive = false
      cleanup?.()
    }
    // `build` and `onProgress` are stable module functions or setters at the call sites.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, wrapper, top])
}

/** The page scroll position for a point (0–1) of a story whose wrapper is `wrapper` (see `useScrollStory`). */
export function storyScrollTarget(wrapper: HTMLElement, progress: number, top = STORY_STAGE_TOP): number {
  const stage = wrapper.firstElementChild as HTMLElement | null
  const start = wrapper.getBoundingClientRect().top + window.scrollY - top
  const distance = wrapper.offsetHeight - (stage?.offsetHeight ?? 0)
  return start + distance * Math.min(0.999, Math.max(0, progress))
}
