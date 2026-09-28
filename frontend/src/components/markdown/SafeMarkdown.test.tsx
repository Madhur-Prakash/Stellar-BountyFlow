import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SafeMarkdown } from './SafeMarkdown'

// The renderer is a lazy chunk; on a busy machine its first import can take a few seconds.
const LOAD_TIMEOUT = 10_000

/** Waits until the plain-text stand-in has been replaced by the rendered Markdown. */
async function rendered(container: HTMLElement) {
  await waitFor(() => expect(container.querySelector('[data-slot="markdown-fallback"]')).toBeNull(), {
    timeout: LOAD_TIMEOUT,
  })
}

describe('SafeMarkdown', () => {
  it('shows the text while the renderer loads, then renders markdown formatting', async () => {
    const { container } = render(<SafeMarkdown>{'## Scope\n\n- **bold** item\n- `code`'}</SafeMarkdown>)
    expect(container.querySelector('[data-slot="markdown-fallback"]')).toHaveTextContent('Scope')
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Scope' }, { timeout: LOAD_TIMEOUT }),
    ).toBeInTheDocument()
    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getByText('code').tagName).toBe('CODE')
  }, 15_000)

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
    const good = await screen.findByRole('link', { name: /good/ }, { timeout: LOAD_TIMEOUT })
    expect(screen.queryByRole('link', { name: /bad/ })).not.toBeInTheDocument()
    expect(screen.getByText('bad')).toBeInTheDocument()
    expect(good).toHaveAttribute('href', 'https://stellar.org')
    expect(good).toHaveAttribute('target', '_blank')
    expect(good.getAttribute('rel')).toContain('noopener')
    expect(good.getAttribute('rel')).toContain('nofollow')
  })

  it('renders images as links instead of loading them', async () => {
    const { container } = render(<SafeMarkdown>{'![diagram](https://example.com/d.png)'}</SafeMarkdown>)
    await rendered(container)
    expect(container.querySelector('img')).toBeNull()
  })

  it('renders nothing for empty input', () => {
    const { container } = render(<SafeMarkdown>{null}</SafeMarkdown>)
    expect(container).toBeEmptyDOMElement()
  })
})
