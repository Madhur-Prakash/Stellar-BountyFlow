import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SafeMarkdown } from './SafeMarkdown'

/** The renderer is lazy-loaded: wait until the plain-text stand-in has been replaced. */
async function rendered(container: HTMLElement) {
  await waitFor(() => expect(container.querySelector('[data-slot="markdown-fallback"]')).toBeNull())
}

describe('SafeMarkdown', () => {
  it('shows the text while the renderer loads, then renders markdown formatting', async () => {
    const { container } = render(<SafeMarkdown>{'## Scope\n\n- **bold** item\n- `code`'}</SafeMarkdown>)
    expect(container.querySelector('[data-slot="markdown-fallback"]')).toHaveTextContent('Scope')
    expect(await screen.findByRole('heading', { level: 2, name: 'Scope' })).toBeInTheDocument()
    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getByText('code').tagName).toBe('CODE')
  })

  it('strips script tags and raw HTML', async () => {
    const { container } = render(
      <SafeMarkdown>
        {
          'Hello <script>window.__pwned = true</script> <img src=x onerror="alert(1)"> <b onclick="x()">raw</b> <iframe src="https://evil.test"></iframe>'
        }
      </SafeMarkdown>,
    )
    await rendered(container)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('iframe')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelector('[onerror],[onclick]')).toBeNull()
    expect(container.innerHTML).not.toMatch(/<script/i)
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it('neutralises javascript: links and hardens external links', async () => {
    render(<SafeMarkdown>{'[bad](javascript:alert(1)) and [good](https://stellar.org)'}</SafeMarkdown>)
    const good = await screen.findByRole('link', { name: /good/ })
    expect(screen.queryByRole('link', { name: /bad/ })).not.toBeInTheDocument()
    expect(screen.getByText('bad')).toBeInTheDocument()
    expect(good).toHaveAttribute('href', 'https://stellar.org')
    expect(good).toHaveAttribute('target', '_blank')
    expect(good.getAttribute('rel')).toContain('noopener')
    expect(good.getAttribute('rel')).toContain('nofollow')
  })

  it('renders images as links instead of loading them', async () => {
    const { container } = render(<SafeMarkdown>{'![diagram](https://example.com/d.png)'}</SafeMarkdown>)
    expect(await screen.findByRole('link', { name: 'diagram' })).toHaveAttribute('href', 'https://example.com/d.png')
    expect(container.querySelector('img')).toBeNull()
  })

  it('renders nothing for empty input', () => {
    const { container } = render(<SafeMarkdown>{null}</SafeMarkdown>)
    expect(container).toBeEmptyDOMElement()
  })
})
