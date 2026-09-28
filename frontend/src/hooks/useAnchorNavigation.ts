import type { MouseEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { scrollToAnchor } from '@/lib/scroll'

/** Handles "/#anchor" links: smooth-scroll in place on the landing page, navigate otherwise. */
export function useAnchorNavigation() {
  const location = useLocation()
  const navigate = useNavigate()
  return (e: MouseEvent<HTMLAnchorElement>, to: string, after?: () => void) => {
    const [path, hash] = to.split('#')
    if (!hash) {
      after?.()
      return
    }
    e.preventDefault()
    after?.()
    if ((path || '/') === location.pathname) {
      scrollToAnchor(hash)
      window.history.replaceState(null, '', `#${hash}`)
    } else {
      navigate(`${path || '/'}#${hash}`)
    }
  }
}
