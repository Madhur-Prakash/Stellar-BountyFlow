import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type LazyExoticComponent,
} from 'react'

import { webglAvailable } from './useThreeTheme'

/** Options a scene may use; each scene ignores the ones it has no use for. */
export type SceneOptions = { density?: number; dotSize?: number; markerScale?: number }

type SceneComponent = LazyExoticComponent<
  ComponentType<SceneOptions & { className?: string; style?: CSSProperties }>
>

// Three.js and React Three Fiber live in these chunks; nothing 3D is in a page's own bundle.
const scenes: Record<'globe' | 'ledger' | 'constellation', SceneComponent> = {
  globe: lazy(() => import('./PaymentsGlobe')),
  ledger: lazy(() => import('./LedgerField')),
  constellation: lazy(() => import('./Constellation')),
}

declare global {
  interface Window {
    __BONEYARD_BUILD?: boolean
  }
}

/** How far before a scene reaches the viewport its chunk starts downloading. */
const PRELOAD_MARGIN = '400px'
/** A breath after it comes into range, so the scene never competes with the page's own rendering. */
const SETTLE_MS = 350

/**
 * A decorative WebGL scene. It is loaded only where WebGL exists, never while skeletons are being captured,
 * and not until it is close to the viewport — three.js is by far the heaviest chunk on the site, so a scene at
 * the foot of a page costs a visitor nothing unless they scroll to it. Until then, and wherever it cannot run,
 * an empty box holds its place.
 */
export function Scene({
  name,
  className,
  style,
  ...options
}: { name: keyof typeof scenes; className?: string; style?: CSSProperties } & SceneOptions) {
  const placeholder = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const el = placeholder.current
    if (!el || window.__BONEYARD_BUILD || !webglAvailable()) return
    let timer = 0
    // Without IntersectionObserver, fall back to loading once the page has settled.
    if (typeof IntersectionObserver === 'undefined') {
      timer = window.setTimeout(() => setReady(true), SETTLE_MS)
      return () => window.clearTimeout(timer)
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        observer.disconnect()
        timer = window.setTimeout(() => setReady(true), SETTLE_MS)
      },
      { rootMargin: PRELOAD_MARGIN },
    )
    observer.observe(el)
    return () => {
      observer.disconnect()
      window.clearTimeout(timer)
    }
  }, [])

  if (!ready) return <div ref={placeholder} aria-hidden className={className} style={style} />
  const Component = scenes[name]
  return (
    <Suspense fallback={null}>
      <Component className={className} style={style} {...options} />
    </Suspense>
  )
}
