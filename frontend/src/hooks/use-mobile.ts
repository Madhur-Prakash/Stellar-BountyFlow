import { useMediaQuery } from './useMediaQuery'

const MOBILE_BREAKPOINT = 768

/** Used by the shadcn Sidebar to switch to its Sheet variant. */
export function useIsMobile() {
  return useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
}
