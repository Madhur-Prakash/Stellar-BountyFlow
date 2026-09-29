import { describe, expect, it } from 'vitest'

import type { Asset, AssetAmount } from '@/lib/api/types'

import {
  InvalidAmountError,
  assetCode,
  addAmounts,
  amountRatio,
  compareAmounts,
  formatAmount,
  formatAmountCompact,
  formatStroops,
  isValidAmount,
  multiplyAmount,
  normalizeAmount,
  parseAmount,
  formatAssetAmounts,
  formatMoney,
  shortAddress,
  subtractAmounts,
  toDecimalString,
  tryParseAmount,
} from './money'

describe('parseAmount', () => {
  it('parses decimal strings into stroops without floats', () => {
    expect(parseAmount('12.5')).toBe(125_000_000n)
    expect(parseAmount('0.0000001')).toBe(1n)
    expect(parseAmount('250.5000000')).toBe(2_505_000_000n)
    expect(parseAmount('1,250.25')).toBe(12_502_500_000n)
    expect(parseAmount('.5')).toBe(5_000_000n)
    expect(parseAmount('7')).toBe(70_000_000n)
    expect(parseAmount('-3.1')).toBe(-31_000_000n)
  })

  it('handles values beyond float precision exactly', () => {
    expect(parseAmount('922337203685.4775807')).toBe(9_223_372_036_854_775_807n)
    expect(toDecimalString(parseAmount('0.1') + parseAmount('0.2'))).toBe('0.3000000')
  })

  it('rejects invalid input and more than 7 decimals', () => {
    expect(() => parseAmount('abc')).toThrow(InvalidAmountError)
    expect(() => parseAmount('')).toThrow(InvalidAmountError)
    expect(() => parseAmount('.')).toThrow(InvalidAmountError)
    expect(() => parseAmount('1.00000001')).toThrow(/7 decimal/)
    expect(() => parseAmount('1e5')).toThrow(InvalidAmountError)
    expect(tryParseAmount('nope')).toBeNull()
    expect(tryParseAmount(null)).toBeNull()
  })
})

describe('formatting', () => {
  it('produces the canonical 7-decimal API string', () => {
    expect(toDecimalString(125_000_000n)).toBe('12.5000000')
    expect(toDecimalString(-1n)).toBe('-0.0000001')
    expect(normalizeAmount('250.5')).toBe('250.5000000')
  })

  it('groups thousands and trims trailing zeros', () => {
    expect(formatAmount('1250.5000000')).toBe('1,250.5')
    expect(formatAmount('1000000')).toBe('1,000,000')
    expect(formatAmount('0.0000001')).toBe('0.0000001')
    expect(formatAmount('12', { minDecimals: 2 })).toBe('12.00')
    expect(formatAmount('1234.5678', { maxDecimals: 2 })).toBe('1,234.56')
    expect(formatAmount('1234', { grouping: false })).toBe('1234')
    expect(formatAmount('5', { asset: 'XLM', signed: true })).toBe('+5 XLM')
    expect(formatAmount('-5.5')).toBe('-5.5')
  })

  it('never renders invalid input as a number', () => {
    expect(formatAmount('garbage')).toBe('—')
    expect(formatAmount(null)).toBe('—')
    expect(formatAmount(undefined)).toBe('—')
  })

  it('formats compact values and stroop fees', () => {
    expect(formatAmountCompact('1234567')).toBe('1.23M')
    expect(formatAmountCompact('1500', 'XLM')).toBe('1.5K XLM')
    expect(formatAmountCompact('999.999')).toBe('999.99')
    expect(formatStroops('100')).toBe('0.00001 XLM')
    expect(formatStroops(null)).toBe('—')
    expect(formatStroops('x')).toBe('—')
  })
})

describe('arithmetic', () => {
  it('multiplies reward by positions', () => {
    expect(multiplyAmount('1250.5', 2)).toBe('2501.0000000')
    expect(multiplyAmount('0.0000001', 3)).toBe('0.0000003')
    expect(multiplyAmount('10', 0n)).toBe('0.0000000')
    expect(() => multiplyAmount('1', 1.5)).toThrow(InvalidAmountError)
  })

  it('adds, subtracts and compares', () => {
    expect(addAmounts('0.1', '0.2', '0.0000001')).toBe('0.3000001')
    expect(subtractAmounts('10', '0.0000001')).toBe('9.9999999')
    expect(compareAmounts('1.0', '1')).toBe(0)
    expect(compareAmounts('1.0000001', '1')).toBe(1)
    expect(compareAmounts('0.5', '2')).toBe(-1)
  })

  it('validates user input', () => {
    expect(isValidAmount('10.5')).toBe(true)
    expect(isValidAmount('0')).toBe(false)
    expect(isValidAmount('0', { allowZero: true })).toBe(true)
    expect(isValidAmount('-1')).toBe(false)
    expect(isValidAmount('1.123456789')).toBe(false)
  })

  it('computes display ratios safely', () => {
    expect(amountRatio('50', '200')).toBe(0.25)
    expect(amountRatio('300', '200')).toBe(1)
    expect(amountRatio('0', '200')).toBe(0)
    expect(amountRatio('10', '0')).toBe(0)
    expect(amountRatio(null, '10')).toBe(0)
  })
})

const asset = (code: string, identifier: string): Asset => ({
  code,
  issuer: identifier === 'native' ? null : identifier.split(':')[1]!,
  type: identifier === 'native' ? 'native' : 'credit_alphanum4',
  contract_id: null,
  identifier,
  decimals: 7,
})

const XLM = asset('XLM', 'native')
const USDC = asset('USDC', 'USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5')

describe('assets', () => {
  it('names the asset an amount is in, defaulting to XLM', () => {
    expect(assetCode(USDC)).toBe('USDC')
    expect(assetCode('EURC')).toBe('EURC')
    expect(assetCode(null)).toBe('XLM')
    expect(assetCode(undefined)).toBe('XLM')
  })

  it('formats an amount with its asset', () => {
    expect(formatMoney('20.5000000', USDC)).toBe('20.5 USDC')
    expect(formatMoney('1250.5', XLM, { maxDecimals: 2 })).toBe('1,250.5 XLM')
    expect(formatMoney(null, USDC)).toBe('—')
  })

  it('lists per-asset totals without ever adding assets together', () => {
    const rows: AssetAmount[] = [
      { asset: XLM, amount: '12.5000000' },
      { asset: USDC, amount: '20.0000000' },
    ]
    expect(formatAssetAmounts(rows)).toBe('12.5 XLM, 20 USDC')
    expect(formatAssetAmounts([{ asset: USDC, amount: '0.0000000' }])).toBe('0 XLM')
    expect(formatAssetAmounts([])).toBe('0 XLM')
    expect(formatAssetAmounts(undefined)).toBe('0 XLM')
  })

  it('shortens addresses for labels', () => {
    expect(shortAddress('GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5')).toBe('GBBD…LFLA5')
    expect(shortAddress('GBBD47IF')).toBe('GBBD47IF')
    expect(shortAddress(null)).toBe('')
  })
})
