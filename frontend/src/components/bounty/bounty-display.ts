import type { BountySummary } from '@/lib/api/types'

/** Public URL of a bounty (slug when there is one). */
export const bountyHref = (b: Pick<BountySummary, 'id' | 'slug'>) => `/bounties/${b.slug || b.id}`

export const applicantsLabel = (n: number) => `${n} applicant${n === 1 ? '' : 's'}`

export const openPositionsOf = (b: Pick<BountySummary, 'positions_available' | 'positions_filled'>) =>
  Math.max(0, b.positions_available - b.positions_filled)
