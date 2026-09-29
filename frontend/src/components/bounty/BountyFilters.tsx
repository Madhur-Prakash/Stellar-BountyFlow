import { X } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  FILTER_RESET,
  PUBLIC_FILTER_STATUSES,
  activeFilterCount,
  type DeadlineWindow,
  type MarketplaceFilters,
} from '@/features/public/marketplace/marketplace-params'
import { useRewardAssets } from '@/lib/api/queries/assets'
import { CATEGORIES, DIFFICULTIES, type BountyStatus, type Category, type Difficulty } from '@/lib/api/types'
import { BOUNTY_STATUS_LABELS, CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { compareAmounts, isValidAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

const ALL = '__all__'

/** Small group label above each block of filters. */
const GROUP_LABEL = 'text-xs font-medium text-muted-foreground'
/** A clickable option row (radio / checkbox with its label). */
const OPTION_ROW =
  '-mx-2 flex min-h-8 items-center gap-2.5 rounded-md px-2 text-sm font-normal transition-colors hover:bg-muted/60'

function Section({ title, children, htmlFor }: { title: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="px-4 py-4">
      <fieldset className="space-y-2.5">
        {htmlFor ? (
          <Label htmlFor={htmlFor} className={GROUP_LABEL}>
            {title}
          </Label>
        ) : (
          <legend className={cn(GROUP_LABEL, 'mb-2.5')}>{title}</legend>
        )}
        {children}
      </fieldset>
    </div>
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
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
      {skills.length > 0 && (
        <ul className="flex flex-wrap gap-1" aria-label="Selected skills">
          {skills.map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={() => onChange(skills.filter((x) => x !== s))}
                className="inline-flex h-6 items-center gap-1 rounded-[4px] border bg-surface/60 pr-1 pl-1.5 text-xs transition-colors hover:border-foreground/25"
                aria-label={`Remove skill ${s}`}
              >
                {s} <X className="size-3 text-muted-foreground" aria-hidden />
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
  unit,
  onChange,
}: {
  min: string
  max: string
  /** Asset code of the selected reward asset; the range applies to it. */
  unit: string | null
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
    <Section title={unit ? `Reward per position (${unit})` : 'Reward per position'}>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-min`} className="text-xs font-normal text-muted-foreground">
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
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-max`} className="text-xs font-normal text-muted-foreground">
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

function RewardAssetFilter({
  id,
  value,
  onChange,
}: {
  id: string
  value: string | null
  onChange: (asset: string | null) => void
}) {
  const { data: assets = [] } = useRewardAssets()
  return (
    <Section title="Reward asset" htmlFor={id}>
      <Select value={value ?? ALL} onValueChange={(v) => onChange(v === ALL ? null : v)}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All assets</SelectItem>
          {value && !assets.some((a) => a.asset.identifier === value) && (
            <SelectItem value={value}>{value === 'native' ? 'XLM' : value.split(':')[0]}</SelectItem>
          )}
          {assets.map((a) => (
            <SelectItem key={a.id} value={a.asset.identifier}>
              {a.asset.code}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Section>
  )
}

/**
 * Marketplace filter panel. Controlled: every change is pushed to the URL by
 * the page, so filtered views are shareable and survive reloads.
 * `header` shows the "Filters" title with a reset button (off inside the mobile sheet, which has its own).
 */
export function BountyFilters({
  filters,
  onChange,
  header = true,
  className,
}: {
  filters: MarketplaceFilters
  onChange: (patch: Partial<MarketplaceFilters>) => void
  header?: boolean
  className?: string
}) {
  const baseId = useId()
  const count = activeFilterCount(filters)
  const { data: assets } = useRewardAssets()
  const assetUnit = filters.asset
    ? (assets?.find((a) => a.asset.identifier === filters.asset)?.asset.code ?? null)
    : null
  const set = (patch: Partial<MarketplaceFilters>) => onChange({ ...patch, page: 1 })
  // Text inputs keep local drafts; remount them when their committed value changes externally.
  const rangeKey = `${filters.minReward}|${filters.maxReward}`

  const toggleStatus = (s: BountyStatus, checked: boolean) =>
    set({ status: checked ? [...filters.status, s] : filters.status.filter((x) => x !== s) })

  return (
    <div className={cn('text-sm', className)} aria-label="Filters" role="group">
      {header && (
        <div className="flex h-12 items-center justify-between gap-2 border-b px-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            Filters
            {count > 0 && (
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-[4px] bg-primary/10 px-1 text-xs font-medium text-primary-emphasis tabular-nums">
                {count}
                <span className="sr-only"> active</span>
              </span>
            )}
          </h2>
          {count > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="-mr-2 h-7 px-2 text-muted-foreground"
              onClick={() => set(FILTER_RESET)}
            >
              Reset
            </Button>
          )}
        </div>
      )}

      <div className="divide-y">
        <Section title="Funding">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor={`${baseId}-funded`} className="text-sm font-normal">
              Funded only
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

        <RewardAssetFilter
          id={`${baseId}-asset`}
          value={filters.asset}
          onChange={(asset) => set({ asset })}
        />

        <RewardRange
          key={rangeKey}
          min={filters.minReward}
          max={filters.maxReward}
          unit={assetUnit}
          onChange={set}
        />

        <SkillsInput skills={filters.skills} onChange={(skills) => set({ skills })} />

        <Section title="Application deadline">
          <RadioGroup
            value={filters.deadline ?? 'any'}
            onValueChange={(v) => set({ deadline: v === 'any' ? null : (v as DeadlineWindow) })}
            className="gap-0"
          >
            {(
              [
                ['any', 'Any time'],
                ['3d', 'Within 3 days'],
                ['7d', 'Within 7 days'],
                ['30d', 'Within 30 days'],
              ] as const
            ).map(([value, label]) => (
              <Label key={value} htmlFor={`${baseId}-dl-${value}`} className={OPTION_ROW}>
                <RadioGroupItem id={`${baseId}-dl-${value}`} value={value} />
                {label}
              </Label>
            ))}
          </RadioGroup>
        </Section>

        <Section title="Status">
          <div className="grid">
            {PUBLIC_FILTER_STATUSES.map((s) => {
              const id = `${baseId}-st-${s}`
              return (
                <Label key={s} htmlFor={id} className={OPTION_ROW}>
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
    </div>
  )
}
