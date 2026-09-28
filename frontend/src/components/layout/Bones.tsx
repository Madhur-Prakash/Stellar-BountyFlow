import { configureBoneyard, Skeleton } from 'boneyard-js/react'
import { useEffect, useState, type ReactNode } from 'react'

import boneyardConfig from '../../../boneyard.config.json'

type Captured = NonNullable<Parameters<typeof Skeleton>[0]['initialBones']>

// Colours and animation for every skeleton, from the same file the capture CLI reads.
configureBoneyard({
  color: boneyardConfig.color,
  darkColor: boneyardConfig.darkColor,
  animate: boneyardConfig.animate as 'shimmer',
  shimmerColor: boneyardConfig.shimmerColor,
  darkShimmerColor: boneyardConfig.darkShimmerColor,
  speed: boneyardConfig.speed,
  transition: boneyardConfig.transition,
})

/**
 * Each view's captured bones are their own small chunk, fetched when the view mounts (in parallel with its data),
 * so the first page load does not carry the skeletons of every page in the app.
 */
const loaders = import.meta.glob<Captured>('../../bones/*.bones.json', { import: 'default' })
const loaded = new Map<string, Captured>()

function useCapturedBones(name: string): Captured | undefined {
  // Re-render once a view's bones arrive; the cache itself is read during render.
  const [, setArrived] = useState<string | null>(null)
  useEffect(() => {
    const load = loaders[`../../bones/${name}.bones.json`]
    if (loaded.has(name) || !load) return
    let live = true
    load()
      .then((b) => {
        loaded.set(name, b)
        if (live) setArrived(name)
      })
      .catch(() => {
        // A skeleton that fails to load leaves the fallback in place.
      })
    return () => {
      live = false
    }
  }, [name])
  return loaded.get(name)
}

/**
 * Loading placeholder captured from the real layout (boneyard). `name` must be unique across the app; its bones
 * are generated from the running app by `pnpm bones` into src/bones. `fallback` renders until bones exist for a
 * name (a new view), while they load, or for an uncaptured breakpoint.
 *
 * Bones are keyed by viewport width, and most views sit inside a sidebar or a padded column, so the breakpoint
 * is chosen by viewport width, as the CLI captured it.
 */
export function Bones({
  name,
  loading,
  fallback,
  className,
  children,
}: {
  name: string
  loading: boolean
  fallback?: ReactNode
  className?: string
  children: ReactNode
}) {
  const bones = useCapturedBones(name)
  return (
    <Skeleton
      name={name}
      loading={loading}
      initialBones={bones}
      fallback={fallback}
      className={className}
      select="viewport"
    >
      {children}
    </Skeleton>
  )
}
