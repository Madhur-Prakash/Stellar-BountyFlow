import { Plus, Trash2 } from 'lucide-react'
import { useFieldArray, useWatch, type Control } from 'react-hook-form'

import { Button } from '@/components/ui/button'
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useEscrowConfig } from '@/lib/api/queries/escrow'
import { formatWindow, sumMilestones, windowUnits, type WindowUnit } from '@/lib/escrow'
import { formatAmount, toDecimalString, tryParseAmount } from '@/lib/money'

import type { BountyFormValues } from './bounty-form-schema'

const HELP = 'text-[0.8125rem]'

const UNIT_LABELS: Record<WindowUnit, string> = { minutes: 'Minutes', hours: 'Hours', days: 'Days' }

/** How long the requester has to answer work the contributor records on-chain, within the server's bounds. */
export function ReviewWindowField({
  control,
  disabled,
}: {
  control: Control<BountyFormValues>
  disabled?: boolean
}) {
  const config = useEscrowConfig()
  const min = config.data?.min_review_window_seconds ?? 86_400
  const max = config.data?.max_review_window_seconds ?? 30 * 86_400
  const units = windowUnits(min)
  return (
    <div className="space-y-2">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,10rem)_minmax(0,10rem)]">
        <FormField
          control={control}
          name="review_window_value"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Review window</FormLabel>
              <FormControl>
                <Input inputMode="numeric" disabled={disabled} {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={control}
          name="review_window_unit"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Unit</FormLabel>
              <Select value={field.value} onValueChange={field.onChange} disabled={disabled}>
                <FormControl>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {(units.includes(field.value) ? units : [...units, field.value]).map((u) => (
                    <SelectItem key={u} value={u}>
                      {UNIT_LABELS[u]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>
      <p className={`${HELP} text-muted-foreground`}>
        When a contributor records work on-chain, you have this long to pay, ask for changes or reject it.
        After that, they can claim the payment from escrow. Between {formatWindow(min)} and{' '}
        {formatWindow(max)}.
      </p>
    </div>
  )
}

/**
 * Split a single-position reward into milestones that add up to it. Each approved milestone is released on
 * its own from the one funded escrow.
 */
export function MilestonesEditor({
  control,
  disabled,
  code,
}: {
  control: Control<BountyFormValues>
  disabled?: boolean
  code: string
}) {
  const { fields, append, remove, replace } = useFieldArray({ control, name: 'milestones' })
  const [reward, positions, milestones] = useWatch({
    control,
    name: ['reward_amount', 'positions_available', 'milestones'],
  })
  const single = positions.trim() === '1'
  const enabled = fields.length > 0
  const total = sumMilestones((milestones ?? []).map((m) => m.amount))
  const rewardStroops = tryParseAmount(reward)
  const rest = total !== null && rewardStroops !== null ? rewardStroops - total : null

  const toggle = (on: boolean) => {
    if (!on) return replace([])
    // Start with two halves of the reward; the requester edits the split.
    const half = rewardStroops !== null && rewardStroops > 1n ? rewardStroops / 2n : null
    replace([
      { title: '', description: '', amount: half !== null ? toDecimalString(half) : '' },
      {
        title: '',
        description: '',
        amount: half !== null && rewardStroops !== null ? toDecimalString(rewardStroops - half) : '',
      },
    ])
  }

  return (
    <div className="space-y-4 rounded-lg border px-4 py-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Pay in milestones</p>
          <p className={`${HELP} text-muted-foreground`}>
            {single
              ? 'Fund the reward once and release it milestone by milestone.'
              : 'Milestones need a single position.'}
          </p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={toggle}
          disabled={disabled || (!single && !enabled)}
          aria-label="Pay in milestones"
        />
      </div>
      {enabled && (
        <>
          <ol className="space-y-3">
            {fields.map((f, i) => (
              <li
                key={f.id}
                className="grid gap-3 rounded-lg bg-surface/60 p-3 sm:grid-cols-[minmax(0,1fr)_9rem_auto]"
              >
                <FormField
                  control={control}
                  name={`milestones.${i}.title`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Milestone {i + 1}</FormLabel>
                      <FormControl>
                        <Input placeholder="e.g. API design approved" disabled={disabled} {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={control}
                  name={`milestones.${i}.amount`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Amount ({code})</FormLabel>
                      <FormControl>
                        <Input inputMode="decimal" disabled={disabled} {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="flex items-end">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={disabled || fields.length <= 2}
                    onClick={() => remove(i)}
                    aria-label={`Remove milestone ${i + 1}`}
                  >
                    <Trash2 />
                  </Button>
                </div>
                <FormField
                  control={control}
                  name={`milestones.${i}.description`}
                  render={({ field }) => (
                    <FormItem className="sm:col-span-3">
                      <FormLabel className="sr-only">Milestone {i + 1} details</FormLabel>
                      <FormControl>
                        <Input placeholder="What is delivered (optional)" disabled={disabled} {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled || fields.length >= 20}
              onClick={() => append({ title: '', description: '', amount: '' })}
            >
              <Plus /> Add milestone
            </Button>
            <p className="text-sm tabular-nums" aria-live="polite">
              {total === null ? (
                <span className="text-muted-foreground">Enter every amount</span>
              ) : rest === 0n ? (
                <span className="text-muted-foreground">
                  Adds up to {formatAmount(toDecimalString(total))} {code}
                </span>
              ) : rest !== null && rest > 0n ? (
                <span className="text-warning">
                  {formatAmount(toDecimalString(rest))} {code} left to assign
                </span>
              ) : (
                <span className="text-destructive">
                  {formatAmount(toDecimalString(-(rest ?? 0n)))} {code} over the reward
                </span>
              )}
            </p>
          </div>
          <FormField
            control={control}
            name="milestones"
            render={() => (
              <FormItem>
                <FormMessage />
              </FormItem>
            )}
          />
        </>
      )}
    </div>
  )
}
