import Lenis from 'lenis'
import { useEffect } from 'react'

import { useScrollEngine } from '@/lib/scroll'

import { motionAllowed } from './useReducedMotion'

// Elements that scroll on their own: wheel and touch over them must not move the page behind.
const OWN_SCROLL =
  '[role="dialog"], [role="alertdialog"], [role="listbox"], [role="menu"], [data-radix-popper-content-wrapper], [data-lenis-prevent], [cmdk-list]'

/**
 * Lenis smooth wheel scrolling on the native window scroll, so `position: sticky`, dialogs and native scrollbars
 * keep working. Used by the public site; the signed-in workspace keeps plain native scrolling. Skipped under
 * reduced motion.
 */
export function useSmoothScroll(enabled = true) {
  useEffect(() => {
    if (!enabled || !motionAllowed()) return

    const lenis = new Lenis({
      autoRaf: true,
      lerp: 0.14,
      smoothWheel: true,
      allowNestedScroll: true,
      prevent: (node) => !!node.closest?.(OWN_SCROLL),
    })

    // Radix marks <body data-scroll-locked> while a dialog, sheet or menu owns scrolling; pause Lenis meanwhile.
    const syncLock = () => (document.body.hasAttribute('data-scroll-locked') ? lenis.stop() : lenis.start())
    const lockObserver = new MutationObserver(syncLock)
    lockObserver.observe(document.body, { attributes: true, attributeFilter: ['data-scroll-locked'] })

    useScrollEngine.getState().set({ lenis })
    return () => {
      lockObserver.disconnect()
      lenis.destroy()
      useScrollEngine.getState().set({ lenis: null })
    }
  }, [enabled])
}
