import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useRewardAssets } from '@/lib/api/queries/assets'

import { NATIVE, rewardAssetLabel } from './asset-display'

/** Reward asset picker for a bounty: every enabled asset on this network. */
export function RewardAssetSelect({
  value,
  onChange,
  disabled,
  id,
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
}: {
  value: string
  onChange: (identifier: string) => void
  disabled?: boolean
  id?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}) {
  const { data: assets = [], isPending } = useRewardAssets()
  const known = assets.some((a) => a.asset.identifier === value)
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled || isPending}>
      <SelectTrigger
        id={id}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        className="w-full min-w-0 *:data-[slot=select-value]:block *:data-[slot=select-value]:truncate"
      >
        <SelectValue placeholder={isPending ? 'Loading assets…' : 'Choose an asset'} />
      </SelectTrigger>
      <SelectContent>
        {!known && value && (
          <SelectItem value={value} disabled>
            {value === NATIVE ? 'XLM' : value.split(':')[0]}
          </SelectItem>
        )}
        {assets.map((a) => (
          <SelectItem key={a.id} value={a.asset.identifier}>
            {rewardAssetLabel(a, assets)}
            <span className="text-muted-foreground">
              {a.name && a.name !== a.asset.code ? `, ${a.name}` : ''}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
