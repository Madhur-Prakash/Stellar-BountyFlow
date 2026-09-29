import type { AssetAmount, DecimalString } from '@/lib/api/types'
import { formatAmount, formatMoney } from '@/lib/money'

/**
 * A money total that can span several reward assets. Amounts of different assets are never added together: the
 * largest-listed asset leads and the rest follow on their own line. `fallback` is the XLM-only scalar the API
 * has always returned, used when a response carries no per-asset breakdown.
 */
export function AssetTotals({
  rows,
  fallback,
  maxDecimals = 2,
}: {
  rows: AssetAmount[] | undefined
  fallback: DecimalString
  maxDecimals?: number
}) {
  const [first, ...rest] = rows ?? []
  if (!first) {
    return (
      <>
        {formatAmount(fallback, { maxDecimals })}{' '}
        <span className="text-sm font-normal text-muted-foreground">XLM</span>
      </>
    )
  }
  return (
    <>
      {formatAmount(first.amount, { maxDecimals })}{' '}
      <span className="text-sm font-normal text-muted-foreground">{first.asset.code}</span>
      {rest.length > 0 && (
        <span className="block text-sm font-normal text-muted-foreground">
          {rest.map((r) => formatMoney(r.amount, r.asset, { maxDecimals })).join(', ')}
        </span>
      )}
    </>
  )
}
