import type { AlertFrequency, BountySort, SavedSearch, SavedSearchFilters } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS, CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { formatAmount } from '@/lib/money'

import {
  DEADLINE_WINDOWS,
  DEFAULT_FILTERS,
  FOR_YOU,
  serializeFilters,
  type DeadlineWindow,
  type MarketplaceFilters,
} from './marketplace-params'

/** URL parameter naming the saved search the marketplace is showing. */
export const SAVED_PARAM = 'saved'

export const FREQUENCY_LABELS: Record<AlertFrequency, string> = {
  INSTANT: 'Instant',
  DAILY: 'Daily digest',
  WEEKLY: 'Weekly digest',
  OFF: 'Off',
}

/** The marketplace's current filters as a saved search stores them (deadline as a rolling window). */
export function filtersToSaved(f: MarketplaceFilters): SavedSearchFilters {
  const saved: SavedSearchFilters = { funded_only: f.fundedOnly }
  if (f.q.trim()) saved.q = f.q.trim()
  if (f.category) saved.category = [f.category]
  if (f.difficulty) saved.difficulty = [f.difficulty]
  if (f.status.length) saved.status = f.status
  if (f.skills.length) saved.skills = f.skills
  if (f.minReward) saved.min_reward = f.minReward
  if (f.maxReward) saved.max_reward = f.maxReward
  if (f.asset) saved.asset = [f.asset]
  if (f.deadline) saved.deadline_within_days = DEADLINE_WINDOWS[f.deadline]
  // "For you" is not a list sort, so it is not saved; the search opens with the default order.
  if (f.sort && f.sort !== FOR_YOU) saved.sort = f.sort as BountySort
  return saved
}

/** Display code of a reward asset identifier: "native" is XLM, "CODE:ISSUER" shows its code. */
function assetLabel(identifier: string): string {
  return identifier === 'native' ? 'XLM' : (identifier.split(':')[0] ?? identifier)
}

function windowFor(days: number | null | undefined): DeadlineWindow | null {
  if (!days) return null
  const windows = Object.entries(DEADLINE_WINDOWS) as [DeadlineWindow, number][]
  return (windows.find(([, d]) => d >= days) ?? windows[windows.length - 1]!)[0]
}

/** A saved search back into marketplace filters (first page). */
export function savedToFilters(s: SavedSearchFilters): MarketplaceFilters {
  return {
    ...DEFAULT_FILTERS,
    q: s.q ?? '',
    category: s.category?.[0] ?? null,
    difficulty: s.difficulty?.[0] ?? null,
    status: s.status ?? [],
    skills: s.skills ?? [],
    minReward: s.min_reward ? formatAmount(s.min_reward).replaceAll(',', '') : '',
    maxReward: s.max_reward ? formatAmount(s.max_reward).replaceAll(',', '') : '',
    deadline: windowFor(s.deadline_within_days),
    fundedOnly: !!s.funded_only,
    asset: s.asset?.[0] ?? null,
    sort: s.sort ?? null,
    page: 1,
  }
}

/** The marketplace URL that opens a saved search (and marks it as looked at). */
export function savedSearchHref(search: Pick<SavedSearch, 'id' | 'filters'>): string {
  const sp = serializeFilters(savedToFilters(search.filters))
  sp.set(SAVED_PARAM, search.id)
  return `/bounties?${sp.toString()}`
}

/** True when two filter sets list the same bounties in the same order (the page is ignored). */
export function sameFilters(a: MarketplaceFilters, b: MarketplaceFilters): boolean {
  const key = (f: MarketplaceFilters) =>
    serializeFilters({ ...f, page: 1, sort: f.sort === FOR_YOU ? null : f.sort }).toString()
  return key(a) === key(b)
}

/** A starting name for "Save search": the text searched, else the skills, else the category. */
export function defaultSearchName(f: MarketplaceFilters): string {
  const name =
    f.q.trim() ||
    f.skills.join(', ') ||
    (f.category ? `${CATEGORY_LABELS[f.category]} bounties` : '') ||
    (f.difficulty ? `${DIFFICULTY_LABELS[f.difficulty]} bounties` : '') ||
    (f.fundedOnly ? 'Funded bounties' : 'All bounties')
  return name.slice(0, 80)
}

/** Short, plain descriptions of what a saved search filters on, for the saved-search list. */
export function describeFilters(s: SavedSearchFilters): string[] {
  const parts: string[] = []
  if (s.q) parts.push(`“${s.q}”`)
  for (const c of s.category ?? []) parts.push(CATEGORY_LABELS[c])
  for (const d of s.difficulty ?? []) parts.push(DIFFICULTY_LABELS[d])
  if (s.skills?.length) parts.push(`Skills: ${s.skills.join(', ')}`)
  if (s.tags?.length) parts.push(`Tags: ${s.tags.join(', ')}`)
  // The reward range is stated in the asset the search filters on, and never converted between assets.
  const code = s.asset?.length === 1 ? assetLabel(s.asset[0]!) : ''
  const unit = code ? ` ${code}` : ''
  if (s.min_reward && s.max_reward)
    parts.push(`${formatAmount(s.min_reward)} to ${formatAmount(s.max_reward)}${unit}`)
  else if (s.min_reward) parts.push(`At least ${formatAmount(s.min_reward)}${unit}`)
  else if (s.max_reward) parts.push(`Up to ${formatAmount(s.max_reward)}${unit}`)
  if (s.asset?.length && !s.min_reward && !s.max_reward)
    parts.push(`Paid in ${s.asset.map(assetLabel).join(', ')}`)
  if (s.deadline_within_days) parts.push(`Closes within ${s.deadline_within_days} days`)
  if (s.funded_only) parts.push('Funded only')
  if (s.status?.length) parts.push(s.status.map((x) => BOUNTY_STATUS_LABELS[x]).join(', '))
  return parts
}
