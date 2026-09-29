/**
 * Decimal-string money helpers. All arithmetic runs on BigInt base units
 * (1 XLM = 10,000,000 stroops; every Stellar Asset Contract token, USDC
 * included, uses the same 7-decimal precision). Floats are never used for
 * amounts. Amounts of different assets are never added together: always
 * carry the asset (`formatMoney`, `AssetAmount`).
 */
import type { Asset, AssetAmount } from '@/lib/api/types'

export const DECIMALS = 7
export const STROOPS_PER_UNIT = 10n ** BigInt(DECIMALS)

const AMOUNT_RE = /^([+-])?(\d+)?(?:\.(\d*))?$/

export class InvalidAmountError extends Error {
  constructor(input: unknown, reason = 'is not a valid amount') {
    super(`"${String(input)}" ${reason}`)
    this.name = 'InvalidAmountError'
  }
}

/** Parse a decimal string (e.g. "12.5", "1,250.0000001") into stroops. Throws on invalid input. */
export function parseAmount(input: string | bigint): bigint {
  if (typeof input === 'bigint') return input
  const s = String(input)
    .trim()
    .replace(/[,_\s]/g, '')
  const m = AMOUNT_RE.exec(s)
  if (!s || !m || (m[2] === undefined && (m[3] === undefined || m[3] === ''))) {
    throw new InvalidAmountError(input)
  }
  const [, sign, whole = '0', frac = ''] = m
  if (frac.length > DECIMALS) throw new InvalidAmountError(input, `has more than ${DECIMALS} decimal places`)
  const stroops = BigInt(whole) * STROOPS_PER_UNIT + BigInt(frac.padEnd(DECIMALS, '0') || '0')
  return sign === '-' ? -stroops : stroops
}

/** Like parseAmount but returns null instead of throwing. */
export function tryParseAmount(input: string | bigint | null | undefined): bigint | null {
  if (input === null || input === undefined) return null
  try {
    return parseAmount(input)
  } catch {
    return null
  }
}

/** True for a non-negative decimal string with at most 7 fraction digits. */
export function isValidAmount(input: string, { allowZero = false }: { allowZero?: boolean } = {}): boolean {
  const v = tryParseAmount(input)
  if (v === null) return false
  return allowZero ? v >= 0n : v > 0n
}

/** Canonical API representation: always 7 fractional digits, e.g. "250.5000000". */
export function toDecimalString(stroops: bigint): string {
  const neg = stroops < 0n
  const abs = neg ? -stroops : stroops
  const whole = abs / STROOPS_PER_UNIT
  const frac = (abs % STROOPS_PER_UNIT).toString().padStart(DECIMALS, '0')
  return `${neg ? '-' : ''}${whole.toString()}.${frac}`
}

/** Normalise any accepted input into the canonical 7-decimal string. */
export function normalizeAmount(input: string | bigint): string {
  return toDecimalString(parseAmount(input))
}

function groupThousands(digits: string, separator = ','): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, separator)
}

export type FormatAmountOptions = {
  /** Minimum fraction digits to show (default 0). */
  minDecimals?: number
  /** Maximum fraction digits to show (default 7). Extra digits are truncated toward zero, never rounded up. */
  maxDecimals?: number
  /** Thousands separators (default true). */
  grouping?: boolean
  /** Append an asset code, e.g. "XLM". */
  asset?: string
  /** Show an explicit "+" for positive values. */
  signed?: boolean
}

/**
 * Human formatting with grouping and up to 7 decimals.
 * formatAmount("1250.5000000") → "1,250.5"; formatAmount("0.0000001") → "0.0000001".
 * Invalid input is rendered as an em dash rather than a misleading number.
 */
export function formatAmount(
  value: string | bigint | null | undefined,
  opts: FormatAmountOptions = {},
): string {
  const { minDecimals = 0, maxDecimals = DECIMALS, grouping = true, asset, signed = false } = opts
  const stroops = tryParseAmount(value ?? null)
  if (stroops === null) return '—'
  const neg = stroops < 0n
  const abs = neg ? -stroops : stroops
  const whole = (abs / STROOPS_PER_UNIT).toString()
  let frac = (abs % STROOPS_PER_UNIT).toString().padStart(DECIMALS, '0')
  const max = Math.max(0, Math.min(DECIMALS, maxDecimals))
  const min = Math.max(0, Math.min(max, minDecimals))
  frac = frac.slice(0, max)
  while (frac.length > min && frac.endsWith('0')) frac = frac.slice(0, -1)
  const sign = neg ? '-' : signed && abs > 0n ? '+' : ''
  const body = `${grouping ? groupThousands(whole) : whole}${frac ? `.${frac}` : ''}`
  return `${sign}${body}${asset ? ` ${asset}` : ''}`
}

/** Compact display for large headline numbers: 1.2K, 3.45M (truncated, never rounded up). */
export function formatAmountCompact(value: string | bigint | null | undefined, asset?: string): string {
  const stroops = tryParseAmount(value ?? null)
  if (stroops === null) return '—'
  const abs = stroops < 0n ? -stroops : stroops
  const units: [bigint, string][] = [
    [10n ** 9n, 'B'],
    [10n ** 6n, 'M'],
    [10n ** 3n, 'K'],
  ]
  for (const [size, suffix] of units) {
    const threshold = size * STROOPS_PER_UNIT
    if (abs >= threshold) {
      const scaled = (stroops * 100n) / threshold // two decimals
      const txt = formatAmount(toDecimalString(scaled * (STROOPS_PER_UNIT / 100n)), { maxDecimals: 2 })
      return `${txt}${suffix}${asset ? ` ${asset}` : ''}`
    }
  }
  return formatAmount(stroops, { maxDecimals: 2, asset })
}

type AssetLike = Pick<Asset, 'code'> | string | null | undefined

/** The asset code to print next to an amount ("XLM" when unknown, as for pre-asset rows). */
export function assetCode(asset: AssetLike): string {
  if (!asset) return 'XLM'
  return typeof asset === 'string' ? asset : asset.code
}

/** An amount with its asset code, e.g. formatMoney("20.5000000", usdc) → "20.5 USDC". */
export function formatMoney(
  value: string | bigint | null | undefined,
  asset: AssetLike,
  opts: Omit<FormatAmountOptions, 'asset'> = {},
): string {
  return formatAmount(value, { ...opts, asset: assetCode(asset) })
}

/** Per-asset totals as one line, XLM first: "12 XLM, 20 USDC". Empty → "0 XLM" (nothing was paid). */
export function formatAssetAmounts(
  rows: AssetAmount[] | null | undefined,
  opts: Omit<FormatAmountOptions, 'asset'> = {},
): string {
  const nonZero = (rows ?? []).filter((r) => tryParseAmount(r.amount) !== 0n)
  if (nonZero.length === 0) return formatMoney('0', 'XLM', opts)
  return nonZero.map((r) => formatMoney(r.amount, r.asset, opts)).join(', ')
}

/** "GBBD…LFLA5": short form of an issuer or contract address for labels. */
export function shortAddress(address: string | null | undefined): string {
  if (!address) return ''
  return address.length > 12 ? `${address.slice(0, 4)}…${address.slice(-5)}` : address
}

/** Stroops (integer string, e.g. fee estimates) → formatted XLM. */
export function formatStroops(stroops: string | bigint | null | undefined, asset = 'XLM'): string {
  if (stroops === null || stroops === undefined || stroops === '') return '—'
  try {
    const v = typeof stroops === 'bigint' ? stroops : BigInt(String(stroops).trim())
    return formatAmount(v, { asset })
  } catch {
    return '—'
  }
}

export function addAmounts(...values: (string | bigint)[]): string {
  return toDecimalString(values.reduce<bigint>((acc, v) => acc + parseAmount(v), 0n))
}

export function subtractAmounts(a: string | bigint, b: string | bigint): string {
  return toDecimalString(parseAmount(a) - parseAmount(b))
}

/** amount × integer multiplier (e.g. reward per position × positions). */
export function multiplyAmount(amount: string | bigint, multiplier: number | bigint): string {
  if (
    typeof multiplier === 'number' &&
    (!Number.isInteger(multiplier) || !Number.isSafeInteger(multiplier))
  ) {
    throw new InvalidAmountError(multiplier, 'is not a safe integer multiplier')
  }
  return toDecimalString(parseAmount(amount) * BigInt(multiplier))
}

/** -1 | 0 | 1 */
export function compareAmounts(a: string | bigint, b: string | bigint): -1 | 0 | 1 {
  const x = parseAmount(a)
  const y = parseAmount(b)
  return x === y ? 0 : x < y ? -1 : 1
}

export const isZeroAmount = (v: string | bigint) => parseAmount(v) === 0n
export const isPositiveAmount = (v: string | bigint) => parseAmount(v) > 0n

/**
 * part / whole as a display ratio in [0, 1] with 4-digit precision.
 * Only used for progress bars — never for money math.
 */
export function amountRatio(
  part: string | bigint | null | undefined,
  whole: string | bigint | null | undefined,
): number {
  const p = tryParseAmount(part ?? null)
  const w = tryParseAmount(whole ?? null)
  if (p === null || w === null || w <= 0n || p <= 0n) return 0
  if (p >= w) return 1
  return Number((p * 10_000n) / w) / 10_000
}
