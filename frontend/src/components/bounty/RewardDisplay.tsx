import { formatAmount } from '@/lib/money'
import { cn } from '@/lib/utils'

/**
 * Reward per position (primary) with the total escrow requirement when there
 * is more than one position. Values are decimal strings; no float math.
 */
export function RewardDisplay({
  rewardAmount,
  totalReward,
  positions,
  assetCode = 'XLM',
  size = 'md',
  className,
}: {
  rewardAmount: string
  totalReward: string
  positions: number
  assetCode?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <div className="flex items-baseline gap-1">
        <span
          className={cn(
            'amount leading-none',
            size === 'sm' && 'text-lg',
            size === 'md' && 'text-[1.375rem]',
            size === 'lg' && 'text-[1.625rem]',
          )}
        >
          {formatAmount(rewardAmount)}
        </span>
        <span className={cn('font-medium text-muted-foreground', size === 'sm' ? 'text-xs' : 'text-sm')}>
          {assetCode}
        </span>
      </div>
      {positions > 1 && (
        <div className={cn('text-xs text-muted-foreground tabular-nums', size === 'sm' ? 'mt-1' : 'mt-1.5')}>
          {positions} positions, {formatAmount(totalReward)} {assetCode} total
        </div>
      )}
    </div>
  )
}
