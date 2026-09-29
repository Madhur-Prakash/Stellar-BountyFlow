import type { RecommendationReason } from '@/lib/api/types'

function list(items: string[], max = 3): string {
  const shown = items.slice(0, max).join(', ')
  return items.length > max ? `${shown} and ${items.length - max} more` : shown
}

/** "Matches rust, soroban" (skills the user has), else "Related to rust" (reached through the skill graph). */
export function reasonText(reason: RecommendationReason | null | undefined): string | null {
  if (!reason) return null
  if (reason.matched_skills.length) return `Matches ${list(reason.matched_skills)}`
  const via = Array.from(new Set(reason.related_skills.map((r) => r.via)))
  return via.length ? `Related to ${list(via)}` : null
}
