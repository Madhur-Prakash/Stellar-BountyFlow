import {
  BOUNTY_SORTS,
  BOUNTY_STATUSES,
  CATEGORIES,
  DIFFICULTIES,
  type BountyListParams,
  type BountySort,
  type BountyStatus,
  type Category,
  type Difficulty,
} from '@/lib/api/types'
import { isValidAmount } from '@/lib/money'

/** Deadline windows offered in the UI (stored in the URL as the key). */
export const DEADLINE_WINDOWS = { '3d': 3, '7d': 7, '30d': 30 } as const
export type DeadlineWindow = keyof typeof DEADLINE_WINDOWS

/** "For you": skill-graph recommendations for a signed-in user (served by /recommendations, not a list sort). */
export const FOR_YOU = 'for_you' as const
export type MarketplaceSort = BountySort | typeof FOR_YOU
const MARKETPLACE_SORTS: readonly MarketplaceSort[] = [...BOUNTY_SORTS, FOR_YOU]

export type MarketplaceFilters = {
  q: string
  category: Category | null
  difficulty: Difficulty | null
  status: BountyStatus[]
  skills: string[]
  minReward: string
  maxReward: string
  deadline: DeadlineWindow | null
  fundedOnly: boolean
  /** Reward asset identifier ("native" or "CODE:ISSUER"); null = every asset. */
  asset: string | null
  /** null = API default: `relevance` when searching, otherwise `newest`. */
  sort: MarketplaceSort | null
  page: number
}

export const DEFAULT_FILTERS: MarketplaceFilters = {
  q: '',
  category: null,
  difficulty: null,
  status: [],
  skills: [],
  minReward: '',
  maxReward: '',
  deadline: null,
  fundedOnly: false,
  asset: null,
  sort: null,
  page: 1,
}

/** Patch that clears every panel filter (search and sort are kept). */
export const FILTER_RESET: Partial<MarketplaceFilters> = {
  category: null,
  difficulty: null,
  status: [],
  skills: [],
  minReward: '',
  maxReward: '',
  deadline: null,
  fundedOnly: false,
  asset: null,
}

/** The sort actually applied (mirrors the API default). */
export function effectiveSort(f: Pick<MarketplaceFilters, 'q' | 'sort'>): MarketplaceSort {
  if (f.sort === 'relevance' && !f.q.trim()) return 'newest'
  return f.sort ?? (f.q.trim() ? 'relevance' : 'newest')
}

/** Statuses a visitor can filter by (drafts are never public). */
export const PUBLIC_FILTER_STATUSES: BountyStatus[] = BOUNTY_STATUSES.filter((s) => s !== 'DRAFT')

export const PAGE_SIZE = 12

const oneOf = <T extends string>(list: readonly T[], v: string | null): T | null =>
  v && (list as readonly string[]).includes(v) ? (v as T) : null

const splitList = (v: string | null) =>
  (v ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

/** "native" or "CODE:ISSUER" (1–12 letters or digits, then a G… account). */
const ASSET_RE = /^(native|[A-Za-z0-9]{1,12}:G[A-Z2-7]{55})$/

/** URLSearchParams → validated filters (unknown / invalid values are dropped). */
export function parseFilters(sp: URLSearchParams): MarketplaceFilters {
  const page = Number.parseInt(sp.get('page') ?? '1', 10)
  const min = sp.get('min_reward') ?? ''
  const max = sp.get('max_reward') ?? ''
  return {
    q: (sp.get('q') ?? '').slice(0, 200),
    category: oneOf(CATEGORIES, sp.get('category')),
    difficulty: oneOf(DIFFICULTIES, sp.get('difficulty')),
    status: splitList(sp.get('status')).filter((s): s is BountyStatus =>
      (PUBLIC_FILTER_STATUSES as string[]).includes(s),
    ),
    skills: splitList(sp.get('skills')).slice(0, 20),
    minReward: min && isValidAmount(min, { allowZero: true }) ? min : '',
    maxReward: max && isValidAmount(max, { allowZero: true }) ? max : '',
    deadline: oneOf(Object.keys(DEADLINE_WINDOWS) as DeadlineWindow[], sp.get('deadline')),
    fundedOnly: sp.get('funded_only') === 'true',
    asset: ASSET_RE.test(sp.get('asset') ?? '') ? sp.get('asset') : null,
    sort: oneOf(MARKETPLACE_SORTS, sp.get('sort')),
    page: Number.isFinite(page) && page > 0 ? page : 1,
  }
}

/** Filters → URLSearchParams (defaults omitted to keep URLs short and shareable). */
export function serializeFilters(f: MarketplaceFilters): URLSearchParams {
  const sp = new URLSearchParams()
  if (f.q.trim()) sp.set('q', f.q.trim())
  if (f.category) sp.set('category', f.category)
  if (f.difficulty) sp.set('difficulty', f.difficulty)
  if (f.status.length) sp.set('status', f.status.join(','))
  if (f.skills.length) sp.set('skills', f.skills.join(','))
  if (f.minReward) sp.set('min_reward', f.minReward)
  if (f.maxReward) sp.set('max_reward', f.maxReward)
  if (f.deadline) sp.set('deadline', f.deadline)
  if (f.fundedOnly) sp.set('funded_only', 'true')
  if (f.asset) sp.set('asset', f.asset)
  if (f.sort) sp.set('sort', f.sort)
  if (f.page > 1) sp.set('page', String(f.page))
  return sp
}

/** Filters → API query params. `now` is injectable for deterministic tests. */
export function toApiParams(f: MarketplaceFilters, now: Date = new Date()): BountyListParams {
  const sort = effectiveSort(f)
  // "For you" has no list sort: the marketplace list falls back to the API default.
  const params: BountyListParams = {
    sort: sort === FOR_YOU ? undefined : sort,
    page: f.page,
    page_size: PAGE_SIZE,
  }
  if (f.q.trim()) params.q = f.q.trim()
  if (f.category) params.category = f.category
  if (f.difficulty) params.difficulty = f.difficulty
  if (f.status.length) params.status = f.status
  if (f.skills.length) params.skills = f.skills
  if (f.minReward) params.min_reward = f.minReward
  if (f.maxReward) params.max_reward = f.maxReward
  if (f.fundedOnly) params.funded_only = true
  if (f.asset) params.asset = [f.asset]
  if (f.deadline) {
    const days = DEADLINE_WINDOWS[f.deadline]
    // Floor to the minute so the query key stays stable across re-renders.
    const start = Math.floor(now.getTime() / 60_000) * 60_000
    params.deadline_after = new Date(start).toISOString()
    params.deadline_before = new Date(start + days * 86_400_000).toISOString()
  }
  return params
}

/** Number of active (non-default) filters, excluding search, sort, and page. */
export function activeFilterCount(f: MarketplaceFilters): number {
  return (
    (f.category ? 1 : 0) +
    (f.difficulty ? 1 : 0) +
    (f.status.length ? 1 : 0) +
    (f.skills.length ? 1 : 0) +
    (f.minReward || f.maxReward ? 1 : 0) +
    (f.deadline ? 1 : 0) +
    (f.fundedOnly ? 1 : 0) +
    (f.asset ? 1 : 0)
  )
}
