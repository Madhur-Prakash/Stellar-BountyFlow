import {
  lazy,
  Suspense,
  useEffect,
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

/**
 * A decorative WebGL scene, loaded after the page has settled and only where WebGL exists (and never while
 * skeletons are being captured). Until then, and wherever it can't run, nothing is drawn.
 */
export function Scene({
  name,
  className,
  style,
  ...options
}: { name: keyof typeof scenes; className?: string; style?: CSSProperties } & SceneOptions) {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    if (window.__BONEYARD_BUILD || !webglAvailable()) return
    const timer = window.setTimeout(() => setReady(true), 350)
    return () => window.clearTimeout(timer)
  }, [])
  if (!ready) return null
  const Component = scenes[name]
  return (
    <Suspense fallback={null}>
      <Component className={className} style={style} {...options} />
    </Suspense>
  )
}
