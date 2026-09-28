import { describe, expect, it } from 'vitest'

import { describeUserAgent } from './user-agent'

describe('describeUserAgent', () => {
  it('names the browser and operating system', () => {
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
      ),
    ).toBe('Chrome on Windows')
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
      ),
    ).toBe('Safari on macOS')
    expect(
      describeUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0'),
    ).toBe('Firefox on Windows')
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
      ),
    ).toBe('Edge on Windows')
    expect(
      describeUserAgent(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
      ),
    ).toBe('Safari on iPhone')
  })

  it('falls back to the product token, then to a generic name', () => {
    expect(describeUserAgent('curl/8.21.0')).toBe('curl')
    expect(describeUserAgent(null)).toBe('Unknown device')
  })
})
