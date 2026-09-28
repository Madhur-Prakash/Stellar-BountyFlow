import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router'

import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { motionAllowed } from '@/hooks/useReducedMotion'
import { ScrollModeContext, useSmoothScroll, type ScrollMode } from '@/hooks/useSmoothScroll'
import { scrollToAnchorWhenReady } from '@/lib/scroll'

import { AnimatedOutlet } from './AnimatedOutlet'
import { MarketingFooter } from './MarketingFooter'
import { MarketingHeader } from './MarketingHeader'

/** Long-form story pages get ScrollSmoother (parallax); pages with sticky panels keep native scroll + Lenis. */
const STORY_PAGES = new Set(['/', '/how-it-works', '/about'])

/**
 * Public site shell. The header is fixed outside the smooth-scroll wrapper; everything that scrolls lives in
 * #smooth-content, which ScrollSmoother transforms on story pages and leaves alone elsewhere.
 */
export function MarketingLayout() {
  const location = useLocation()
  const wrapper = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const mode: ScrollMode = STORY_PAGES.has(location.pathname) ? 'smoother' : 'lenis'
  useSmoothScroll(mode, { wrapper, content, routeKey: location.pathname })

  // Arriving at "/#section" from another page: scroll once the target rendered and settled.
  useEffect(() => {
    if (!location.hash) return
    return scrollToAnchorWhenReady(location.hash)
  }, [location.pathname, location.hash])

  return (
    <ScrollModeContext.Provider value={motionAllowed() ? mode : 'none'}>
      <SkipLink />
      <MarketingHeader />
      <div id="smooth-wrapper" ref={wrapper}>
        <div id="smooth-content" ref={content} className="flex min-h-dvh flex-col pt-16">
          <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 outline-none">
            <AnimatedOutlet />
          </main>
          <MarketingFooter />
        </div>
      </div>
    </ScrollModeContext.Provider>
  )
}
