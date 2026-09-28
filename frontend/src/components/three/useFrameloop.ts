import { useEffect, useState, type RefObject } from 'react'

import { motionAllowed } from '@/hooks/useReducedMotion'

/**
 * React Three Fiber frame loop for a decorative scene: animate while it is on screen, stop when it scrolls away
 * or the tab is hidden, and render a single still frame under reduced motion.
 */
export function useFrameloop(host: RefObject<HTMLElement | null>): 'always' | 'never' | 'demand' {
  const animate = motionAllowed()
  const [visible, setVisible] = useState(true)
  useEffect(() => {
    const el = host.current
    if (!el || !animate) return
    let inView = true
    const update = () => setVisible(inView && document.visibilityState === 'visible')
    const io = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting
      update()
    })
    io.observe(el)
    document.addEventListener('visibilitychange', update)
    return () => {
      io.disconnect()
      document.removeEventListener('visibilitychange', update)
    }
  }, [host, animate])
  if (!animate) return 'demand'
  return visible ? 'always' : 'never'
}
