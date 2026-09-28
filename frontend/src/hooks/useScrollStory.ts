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
 * Scrubs a GSAP timeline across a tall wrapper whose child is `position: sticky`. CSS keeps the section in view
 * (no pin spacers), and the timeline advances from the moment the wrapper's top meets the header to the moment
 * its bottom meets the bottom of the screen, so scrolling back plays it in reverse. `build` creates the tweens and
 * returns the timeline; `onProgress` receives 0–1 for anything React renders (step counters, active states).
 * Positions are re-measured whenever the page height changes, because content above loads after this mounts.
 */
export function useScrollStory(
  wrapper: RefObject<HTMLElement | null>,
  enabled: boolean,
  build: (tools: ScrollStoryTools, root: HTMLElement) => gsap.core.Timeline,
  onProgress?: (progress: number) => void,
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
        ScrollTrigger.create({
          trigger: root,
          start: 'top top+=64',
          end: 'bottom bottom',
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
  }, [enabled, wrapper])
}
