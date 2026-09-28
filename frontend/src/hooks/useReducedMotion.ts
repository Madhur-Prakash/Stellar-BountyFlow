import { useMediaQuery } from './useMediaQuery'

/** True when the user asked the OS to minimise motion. */
export function useReducedMotion(): boolean {
  return useMediaQuery('(prefers-reduced-motion: reduce)')
}

/** Non-hook check for imperative code (GSAP setup, smooth scrolling). */
export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/**
 * Whether decorative and scroll-driven motion may run. Off when the user prefers reduced motion, and while the
 * boneyard CLI captures skeletons (`window.__BONEYARD_BUILD`), so it measures the final layout rather than a
 * frame of an entrance animation. Content must always be fully visible when this is false.
 */
export function motionAllowed(): boolean {
  if (typeof window === 'undefined') return false
  if ((window as Window & { __BONEYARD_BUILD?: boolean }).__BONEYARD_BUILD) return false
  return !prefersReducedMotion()
}

/** True on devices with a precise pointer (mouse, trackpad): drag-to-throw interactions are enabled there only. */
export function hasFinePointer(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: fine)').matches
}
