import { RotateCcw, X } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  DEFAULT_FILTERS,
  PUBLIC_FILTER_STATUSES,
  activeFilterCount,
  type DeadlineWindow,
  type MarketplaceFilters,
} from '@/features/public/marketplace/marketplace-params'
import { CATEGORIES, DIFFICULTIES, type BountyStatus, type Category, type Difficulty } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS, CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { compareAmounts, isValidAmount } from '@/lib/money'

const ALL = '__all__'

function Section({ title, children, htmlFor }: { title: string; children: ReactNode; htmlFor?: string }) {
  return (
    <fieldset className="space-y-2.5 border-b pb-5 last:border-b-0">
      {htmlFor ? (
        <Label htmlFor={htmlFor} className="text-sm font-medium">
          {title}
        </Label>
      ) : (
        <legend className="mb-2.5 text-sm font-medium">{title}</legend>
      )}
      {children}
    </fieldset>
  )
}

function SkillsInput({ skills, onChange }: { skills: string[]; onChange: (skills: string[]) => void }) {
  const id = useId()
  const [draft, setDraft] = useState('')
  const add = () => {
    const next = draft
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean)
    if (next.length) onChange(Array.from(new Set([...skills, ...next])).slice(0, 20))
    setDraft('')
  }
  return (
    <Section title="Skills" htmlFor={id}>
      <div className="flex gap-2">
        <Input
          id={id}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          placeholder="e.g. rust, soroban"
          aria-describedby={`${id}-hint`}
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        Press Enter to add. Matches bounties requiring any of these skills.
      </p>
      {skills.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Selected skills">
          {skills.map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={() => onChange(skills.filter((x) => x !== s))}
                className="inline-flex h-7 items-center gap-1 rounded-md border bg-surface-raised px-2 text-xs hover:border-foreground/20"
                aria-label={`Remove skill ${s}`}
              >
                {s} <X className="size-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function RewardRange({
  min,
  max,
  onChange,
}: {
  min: string
  max: string
  onChange: (range: { minReward: string; maxReward: string }) => void
}) {
  const id = useId()
  const [lo, setLo] = useState(min)
  const [hi, setHi] = useState(max)
  const loValid = !lo || isValidAmount(lo, { allowZero: true })
  const hiValid = !hi || isValidAmount(hi, { allowZero: true })
  const orderValid = !lo || !hi || !loValid || !hiValid || compareAmounts(lo, hi) <= 0
  const error =
    !loValid || !hiValid
      ? 'Use a positive amount with up to 7 decimals.'
      : !orderValid
        ? 'Minimum must not exceed maximum.'
        : null

  const commit = () => {
    if (!error) onChange({ minReward: lo.trim(), maxReward: hi.trim() })
  }

  return (
    <Section title="Reward per position (XLM)">
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label htmlFor={`${id}-min`} className="text-xs text-muted-foreground">
            Min
          </Label>
          <Input
            id={`${id}-min`}
            inputMode="decimal"
            value={lo}
            onChange={(e) => setLo(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => e.key === 'Enter' && commit()}
            placeholder="0"
            aria-invalid={!loValid || !orderValid}
            aria-describedby={error ? `${id}-err` : undefined}
            className="tabular-nums"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-max`} className="text-xs text-muted-foreground">
            Max
          </Label>
          <Input
            id={`${id}-max`}
            inputMode="decimal"
            value={hi}
            onChange={(e) => setHi(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => e.key === 'Enter' && commit()}
            placeholder="Any"
            aria-invalid={!hiValid || !orderValid}
            aria-describedby={error ? `${id}-err` : undefined}
            className="tabular-nums"
          />
        </div>
      </div>
      {error && (
        <p id={`${id}-err`} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </Section>
  )
}

/**
 * Marketplace filter panel. Controlled: every change is pushed to the URL by
 * the page, so filtered views are shareable and survive reloads.
 */
export function BountyFilters({
  filters,
  onChange,
}: {
  filters: MarketplaceFilters
  onChange: (patch: Partial<MarketplaceFilters>) => void
}) {
  const baseId = useId()
  const count = activeFilterCount(filters)
  const set = (patch: Partial<MarketplaceFilters>) => onChange({ ...patch, page: 1 })
  // Text inputs keep local drafts; remount them when their committed value changes externally.
  const rangeKey = `${filters.minReward}|${filters.maxReward}`

  const toggleStatus = (s: BountyStatus, checked: boolean) =>
    set({ status: checked ? [...filters.status, s] : filters.status.filter((x) => x !== s) })

  return (
    <div className="space-y-5" aria-label="Filters" role="group">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          Filters{' '}
          {count > 0 && (
            <span className="ml-1 rounded-md bg-primary/15 px-1.5 py-0.5 text-xs text-primary-emphasis tabular-nums">
              {count}
            </span>
          )}
        </h2>
        {count > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              set({
                category: DEFAULT_FILTERS.category,
                difficulty: DEFAULT_FILTERS.difficulty,
                status: [],
                skills: [],
                minReward: '',
                maxReward: '',
                deadline: null,
                fundedOnly: false,
              })
            }
          >
            <RotateCcw /> Reset
          </Button>
        )}
      </div>

      <Section title="Funding">
        <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
          <Label htmlFor={`${baseId}-funded`} className="flex-col items-start gap-0.5">
            <span>Funded only</span>
            <span className="text-xs font-normal text-muted-foreground">
              Rewards already locked in escrow
            </span>
          </Label>
          <Switch
            id={`${baseId}-funded`}
            checked={filters.fundedOnly}
            onCheckedChange={(v) => set({ fundedOnly: v })}
          />
        </div>
      </Section>

      <Section title="Category" htmlFor={`${baseId}-category`}>
        <Select
          value={filters.category ?? ALL}
          onValueChange={(v) => set({ category: v === ALL ? null : (v as Category) })}
        >
          <SelectTrigger id={`${baseId}-category`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All categories</SelectItem>
            {CATEGORIES.map((c) => (
              <SelectItem key={c} value={c}>
                {CATEGORY_LABELS[c]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Section>

      <Section title="Difficulty" htmlFor={`${baseId}-difficulty`}>
        <Select
          value={filters.difficulty ?? ALL}
          onValueChange={(v) => set({ difficulty: v === ALL ? null : (v as Difficulty) })}
        >
          <SelectTrigger id={`${baseId}-difficulty`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any difficulty</SelectItem>
            {DIFFICULTIES.map((d) => (
              <SelectItem key={d} value={d}>
                {DIFFICULTY_LABELS[d]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Section>

      <RewardRange key={rangeKey} min={filters.minReward} max={filters.maxReward} onChange={set} />

      <SkillsInput skills={filters.skills} onChange={(skills) => set({ skills })} />

      <Section title="Application deadline">
        <RadioGroup
          value={filters.deadline ?? 'any'}
          onValueChange={(v) => set({ deadline: v === 'any' ? null : (v as DeadlineWindow) })}
          className="gap-1"
        >
          {(
            [
              ['any', 'Any time'],
              ['3d', 'Within 3 days'],
              ['7d', 'Within 7 days'],
              ['30d', 'Within 30 days'],
            ] as const
          ).map(([value, label]) => (
            <Label
              key={value}
              htmlFor={`${baseId}-dl-${value}`}
              className="flex min-h-10 items-center gap-3 rounded-md px-2 font-normal hover:bg-muted/50"
            >
              <RadioGroupItem id={`${baseId}-dl-${value}`} value={value} />
              {label}
            </Label>
          ))}
        </RadioGroup>
      </Section>

      <Section title="Status">
        <p className="-mt-1 text-xs text-muted-foreground">
          None selected shows everything currently active (open through under review).
        </p>
        <div className="grid gap-1">
          {PUBLIC_FILTER_STATUSES.map((s) => {
            const id = `${baseId}-st-${s}`
            return (
              <Label
                key={s}
                htmlFor={id}
                className="flex min-h-10 items-center gap-3 rounded-md px-2 font-normal hover:bg-muted/50"
              >
                <Checkbox
                  id={id}
                  checked={filters.status.includes(s)}
                  onCheckedChange={(v) => toggleStatus(s, v === true)}
                />
                {BOUNTY_STATUS_LABELS[s]}
              </Label>
            )
          })}
        </div>
      </Section>
    </div>
  )
}
