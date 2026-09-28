import { useEffect } from 'react'
import { useLocation } from 'react-router'

import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { useSmoothScroll } from '@/hooks/useSmoothScroll'
import { scrollToAnchorWhenReady } from '@/lib/scroll'

import { AnimatedOutlet } from './AnimatedOutlet'
import { MarketingFooter } from './MarketingFooter'
import { MarketingHeader } from './MarketingHeader'

/** Public site shell: sticky header, the page, the footer. Lenis smooths wheel scrolling. */
export function MarketingLayout() {
  const location = useLocation()
  useSmoothScroll()

  // Arriving at "/#section" from another page: scroll once the target rendered and settled.
  useEffect(() => {
    if (!location.hash) return
    return scrollToAnchorWhenReady(location.hash)
  }, [location.pathname, location.hash])

  return (
    <div className="flex min-h-dvh flex-col">
      <SkipLink />
      <MarketingHeader />
      <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 outline-none">
        <AnimatedOutlet />
      </main>
      <MarketingFooter />
    </div>
  )
}
