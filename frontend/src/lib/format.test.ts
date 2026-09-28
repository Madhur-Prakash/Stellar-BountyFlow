import { describe, expect, it } from 'vitest'

import { describeActivity } from './format'

describe('describeActivity', () => {
  it('turns action codes into readable phrases', () => {
    expect(describeActivity('submission.approved')).toBe('approved the work')
    expect(describeActivity('submission.approved', true)).toBe('approved work on')
    expect(describeActivity('bounty.open', true)).toBe('published')
    expect(describeActivity('bounty.under_review')).toBe('moved the bounty to Under review')
    expect(describeActivity('something.new_here')).toBe('something new here')
  })
})
