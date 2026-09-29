/**
 * Discovery: saved searches with alerts, skill-graph recommendations and related skills (docs/api.md,
 * "Discovery"). Re-exported from `../types`.
 */
import type {
  BountySort,
  BountyStatus,
  BountySummary,
  Category,
  DecimalString,
  Difficulty,
  ISODateTime,
  Page,
} from '../types'

export const ALERT_FREQUENCIES = ['INSTANT', 'DAILY', 'WEEKLY', 'OFF'] as const
export type AlertFrequency = (typeof ALERT_FREQUENCIES)[number]

/**
 * Marketplace filters as saved. The deadline is a rolling window (`deadline_within_days`), not fixed dates;
 * matching uses exactly the marketplace's own filter semantics.
 */
export type SavedSearchFilters = {
  q?: string | null
  category?: Category[] | null
  difficulty?: Difficulty[] | null
  status?: BountyStatus[] | null
  skills?: string[] | null
  tags?: string[] | null
  min_reward?: DecimalString | null
  max_reward?: DecimalString | null
  deadline_within_days?: number | null
  funded_only?: boolean
  /** Reward asset identifiers ("native", "CODE:ISSUER"), as the marketplace's asset filter uses them. */
  asset?: string[] | null
  sort?: BountySort | null
}

export type SavedSearch = {
  id: string
  name: string
  filters: SavedSearchFilters
  alert_frequency: AlertFrequency
  notify_in_app: boolean
  notify_email: boolean
  is_paused: boolean
  /** Bounties that matched since the search was last opened and that it still lists. */
  new_count: number
  last_viewed_at: ISODateTime
  next_digest_at: ISODateTime | null
  created_at: ISODateTime
  updated_at: ISODateTime
}

export type CreateSavedSearchRequest = {
  name: string
  filters?: SavedSearchFilters
  alert_frequency?: AlertFrequency
  notify_in_app?: boolean
  notify_email?: boolean
}

export type UpdateSavedSearchRequest = Partial<CreateSavedSearchRequest> & { is_paused?: boolean }

export type UnsubscribeResult = { saved_search_id: string; name: string; alert_frequency: AlertFrequency }

export type RelatedMatch = { skill: string; via: string }

export type RecommendationReason = { matched_skills: string[]; related_skills: RelatedMatch[] }

export type Recommendation = { bounty: BountySummary; score: number; reason: RecommendationReason }

export type RecommendationPage = Page<Recommendation> & {
  /** The user's strongest skills the ranking started from. */
  seed_skills: string[]
  has_profile_skills: boolean
}

export type RelatedSkill = {
  skill: string
  weight: number
  via: string[]
  /** Raw skill names to filter the marketplace by; empty when only tags use this skill. */
  marketplace_skills: string[]
}

export type RelatedSkills = { skills: string[]; related: RelatedSkill[]; computed_at: ISODateTime | null }
