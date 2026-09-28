import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SafeMarkdown } from './SafeMarkdown'

describe('SafeMarkdown', () => {
  it('renders markdown formatting', () => {
    render(<SafeMarkdown>{'## Scope\n\n- **bold** item\n- `code`'}</SafeMarkdown>)
    expect(screen.getByRole('heading', { level: 2, name: 'Scope' })).toBeInTheDocument()
    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getByText('code').tagName).toBe('CODE')
  })

  it('strips script tags and raw HTML', () => {
    const { container } = render(
      <SafeMarkdown>
        {
          'Hello <script>window.__pwned = true</script> <img src=x onerror="alert(1)"> <b onclick="x()">raw</b> <iframe src="https://evil.test"></iframe>'
        }
      </SafeMarkdown>,
    )
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('iframe')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelector('[onerror],[onclick]')).toBeNull()
    expect(container.innerHTML).not.toMatch(/<script/i)
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it('neutralises javascript: links and hardens external links', () => {
    render(<SafeMarkdown>{'[bad](javascript:alert(1)) and [good](https://stellar.org)'}</SafeMarkdown>)
    expect(screen.queryByRole('link', { name: /bad/ })).not.toBeInTheDocument()
    expect(screen.getByText('bad')).toBeInTheDocument()
    const good = screen.getByRole('link', { name: /good/ })
    expect(good).toHaveAttribute('href', 'https://stellar.org')
    expect(good).toHaveAttribute('target', '_blank')
    expect(good.getAttribute('rel')).toContain('noopener')
    expect(good.getAttribute('rel')).toContain('nofollow')
  })

  it('renders images as links instead of loading them', () => {
    const { container } = render(<SafeMarkdown>{'![diagram](https://example.com/d.png)'}</SafeMarkdown>)
    expect(container.querySelector('img')).toBeNull()
  })

  it('renders nothing for empty input', () => {
    const { container } = render(<SafeMarkdown>{null}</SafeMarkdown>)
    expect(container).toBeEmptyDOMElement()
  })
})
