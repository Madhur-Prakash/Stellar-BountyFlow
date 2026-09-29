import { format, isValid, parseISO } from 'date-fns'
import { z } from 'zod'

import {
  CATEGORIES,
  DIFFICULTIES,
  VISIBILITIES,
  type BountyDetail,
  type BountyLink,
  type CreateBountyRequest,
} from '@/lib/api/types'
import { DAY_SECONDS, splitWindow, sumMilestones, toSeconds } from '@/lib/escrow'
import { isValidAmount, normalizeAmount, tryParseAmount } from '@/lib/money'

const optionalUrl = z
  .string()
  .trim()
  .refine((v) => v === '' || /^https?:\/\/[^\s]+$/i.test(v), 'Use a full http(s) URL.')

export function parseLinks(text: string): BountyLink[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [label, ...rest] = line.split('|')
      const url = rest.join('|').trim()
      return url ? { label: label!.trim(), url } : { label: '', url: label!.trim() }
    })
}

/** Distinct, non-empty comma-separated entries (matches what the API stores). */
export const csvCount = (v: string) =>
  new Set(
    v
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  ).size

const milestoneSchema = z.object({
  title: z.string().trim().min(3, 'Name the milestone.').max(140, 'Keep it under 140 characters.'),
  description: z.string().max(2000, 'Keep it under 2,000 characters.'),
  amount: z
    .string()
    .trim()
    .refine((v) => isValidAmount(v), 'Enter a positive amount with up to 7 decimals.'),
})

export type MilestoneFormValue = z.infer<typeof milestoneSchema>

export const bountyFormSchema = z
  .object({
    title: z.string().trim().min(8, 'Use at least 8 characters.').max(140, 'Keep it under 140 characters.'),
    short_description: z
      .string()
      .trim()
      .min(20, 'Use at least 20 characters.')
      .max(280, 'Keep it under 280 characters.'),
    description: z.string().trim().min(50, 'Describe the work in at least 50 characters.').max(20000),
    category: z.enum(CATEGORIES),
    difficulty: z.enum(DIFFICULTIES),
    visibility: z.enum(VISIBILITIES),
    tags: z
      .string()
      .max(400)
      .refine((v) => csvCount(v) <= 10, 'Use at most 10 tags.'),
    required_skills: z
      .string()
      .max(400)
      .refine((v) => csvCount(v) <= 15, 'Use at most 15 skills.'),
    reward_amount: z
      .string()
      .trim()
      .refine((v) => isValidAmount(v), 'Enter a positive amount with up to 7 decimals.'),
    /** Reward asset identifier: "native" (XLM) or "CODE:ISSUER". */
    reward_asset: z.string().min(1, 'Choose the asset the reward is paid in.'),
    positions_available: z
      .string()
      .trim()
      .refine((v) => /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 100, 'Between 1 and 100 positions.'),
    application_deadline: z.string(),
    completion_deadline: z.string(),
    eligibility_criteria: z.string().max(5000),
    submission_requirements: z.string().max(5000),
    acceptance_criteria: z
      .string()
      .trim()
      .min(10, 'Say how you’ll judge the work (at least 10 characters).')
      .max(5000),
    repository_url: optionalUrl,
    links: z
      .string()
      .max(3000)
      .refine(
        (v) => parseLinks(v).every((l) => /^https?:\/\/[^\s]+$/i.test(l.url)),
        'Each line must be "Label | https://…".',
      ),
    /** Escrow v2: how long the requester has to answer work recorded on-chain. */
    review_window_value: z
      .string()
      .trim()
      .refine((v) => /^\d+$/.test(v) && Number(v) >= 1, 'Enter a whole number.'),
    review_window_unit: z.enum(['minutes', 'hours', 'days']),
    /** Escrow v2: optional split of a single-position reward. */
    milestones: z.array(milestoneSchema).max(20, 'Use at most 20 milestones.'),
  })
  .refine((v) => v.milestones.length !== 1, {
    path: ['milestones'],
    message: 'Split the reward into at least 2 milestones, or remove the milestone.',
  })
  .refine((v) => v.milestones.length === 0 || v.positions_available.trim() === '1', {
    path: ['milestones'],
    message: 'Milestones need a single position.',
  })
  .refine(
    (v) => {
      if (v.milestones.length === 0) return true
      const total = sumMilestones(v.milestones.map((m) => m.amount))
      const reward = tryParseAmount(v.reward_amount)
      return total !== null && reward !== null && total === reward
    },
    { path: ['milestones'], message: 'The milestones must add up to the reward.' },
  )
  .refine((v) => !v.application_deadline || new Date(v.application_deadline).getTime() > Date.now(), {
    path: ['application_deadline'],
    message: 'Pick a time in the future.',
  })
  .refine(
    (v) =>
      !v.application_deadline ||
      !v.completion_deadline ||
      new Date(v.completion_deadline).getTime() > new Date(v.application_deadline).getTime(),
    { path: ['completion_deadline'], message: 'Work must be due after applications close.' },
  )

export type BountyFormValues = z.infer<typeof bountyFormSchema>

const csv = (v: string) =>
  Array.from(
    new Set(
      v
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
    ),
  ).slice(0, 20)

/** datetime-local value ("2026-10-01T12:00", local time) → ISO UTC, or null. */
export function localInputToIso(v: string): string | null {
  if (!v) return null
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

/** ISO → datetime-local value in the user's timezone. */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = parseISO(iso)
  return isValid(d) ? format(d, "yyyy-MM-dd'T'HH:mm") : ''
}

export function toRequest(v: BountyFormValues): CreateBountyRequest {
  return {
    title: v.title,
    short_description: v.short_description,
    description: v.description,
    category: v.category,
    difficulty: v.difficulty,
    visibility: v.visibility,
    tags: csv(v.tags),
    required_skills: csv(v.required_skills),
    reward_amount: normalizeAmount(v.reward_amount),
    reward_asset: v.reward_asset,
    positions_available: Number(v.positions_available),
    application_deadline: localInputToIso(v.application_deadline),
    completion_deadline: localInputToIso(v.completion_deadline),
    eligibility_criteria: v.eligibility_criteria.trim() || null,
    submission_requirements: v.submission_requirements.trim() || null,
    acceptance_criteria: v.acceptance_criteria.trim() || null,
    repository_url: v.repository_url || null,
    links: parseLinks(v.links),
    review_window_seconds: toSeconds(Number(v.review_window_value), v.review_window_unit),
    milestones: v.milestones.map((m) => ({
      title: m.title.trim(),
      description: m.description.trim() || null,
      amount: normalizeAmount(m.amount),
    })),
  }
}

export const EMPTY_BOUNTY_FORM: BountyFormValues = {
  title: '',
  short_description: '',
  description: '',
  category: 'DEVELOPMENT',
  difficulty: 'INTERMEDIATE',
  visibility: 'PUBLIC',
  tags: '',
  required_skills: '',
  reward_amount: '',
  reward_asset: 'native',
  positions_available: '1',
  application_deadline: '',
  completion_deadline: '',
  eligibility_criteria: '',
  submission_requirements: '',
  acceptance_criteria: '',
  repository_url: '',
  links: '',
  review_window_value: String(7),
  review_window_unit: 'days',
  milestones: [],
}

export function fromBounty(b: BountyDetail): BountyFormValues {
  return {
    title: b.title,
    short_description: b.short_description,
    description: b.description,
    category: b.category,
    difficulty: b.difficulty,
    visibility: b.visibility,
    tags: b.tags.join(', '),
    required_skills: b.required_skills.join(', '),
    reward_amount: b.reward_amount,
    reward_asset: b.reward_asset.identifier ?? 'native',
    positions_available: String(b.positions_available),
    application_deadline: isoToLocalInput(b.application_deadline),
    completion_deadline: isoToLocalInput(b.completion_deadline),
    eligibility_criteria: b.eligibility_criteria ?? '',
    submission_requirements: b.submission_requirements ?? '',
    acceptance_criteria: b.acceptance_criteria ?? '',
    repository_url: b.repository_url ?? '',
    links: b.links.map((l) => (l.label ? `${l.label} | ${l.url}` : l.url)).join('\n'),
    ...(() => {
      const w = splitWindow(b.review_window_seconds ?? 7 * DAY_SECONDS)
      return { review_window_value: String(w.value), review_window_unit: w.unit }
    })(),
    milestones: (b.milestones ?? []).map((m) => ({
      title: m.title,
      description: m.description ?? '',
      amount: m.amount,
    })),
  }
}
