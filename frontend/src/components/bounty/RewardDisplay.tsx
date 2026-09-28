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
      <div className="flex items-baseline gap-1.5">
        <span
          className={cn(
            'amount leading-none',
            size === 'sm' && 'text-lg',
            size === 'md' && 'text-[1.625rem]',
            size === 'lg' && 'text-[2.25rem]',
          )}
        >
          {formatAmount(rewardAmount)}
        </span>
        <span className="text-sm font-medium text-muted-foreground">{assetCode}</span>
      </div>
      <div className="text-xs text-muted-foreground tabular-nums">
        {positions > 1 ? (
          <>
            each for {positions} positions, {formatAmount(totalReward)} {assetCode} total
          </>
        ) : (
          'single position'
        )}
      </div>
    </div>
  )
}
