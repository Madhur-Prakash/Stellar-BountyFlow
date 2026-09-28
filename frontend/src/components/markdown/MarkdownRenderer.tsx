import Markdown, { type Components } from 'react-markdown'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'

/**
 * The Markdown renderer behind SafeMarkdown, in its own chunk so react-markdown and its plugins load only on pages
 * that show Markdown.
 *
 * - Raw HTML is never parsed (react-markdown ignores it without rehype-raw), and rehype-sanitize strips anything
 *   outside a strict allow-list.
 * - Links open in a new tab with rel="noopener noreferrer nofollow".
 * - Only http(s)/mailto URLs survive; images are shown as links (no tracking pixels).
 */
const schema = {
  ...defaultSchema,
  tagNames: (defaultSchema.tagNames ?? []).filter(
    (t) => !['img', 'input', 'iframe', 'video', 'audio'].includes(t),
  ),
  protocols: { ...defaultSchema.protocols, href: ['http', 'https', 'mailto'] },
}

const SAFE_HREF = /^(https?:|mailto:|#|\/(?!\/))/i

const components: Components = {
  a: ({ href, children, node: _node, ...rest }) => {
    const safe = href && SAFE_HREF.test(href) ? href : undefined
    if (!safe) return <span>{children}</span>
    const external = /^https?:/i.test(safe)
    return (
      <a
        {...rest}
        href={safe}
        target={external ? '_blank' : undefined}
        rel={external ? 'noopener noreferrer nofollow' : 'nofollow'}
        className="font-medium text-primary-emphasis underline underline-offset-4 hover:text-foreground"
      >
        {children}
        {external && <span className="sr-only"> (opens in a new tab)</span>}
      </a>
    )
  },
  img: ({ src, alt }) =>
    typeof src === 'string' && /^https?:/i.test(src) ? (
      <a
        href={src}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="text-primary-emphasis underline"
      >
        {alt || 'Image'}
      </a>
    ) : null,
  table: ({ node: _node, ...props }) => (
    <div className="my-4 overflow-x-auto rounded-lg border">
      <table {...props} className="w-full text-sm" />
    </div>
  ),
}

export default function MarkdownRenderer({ children }: { children: string }) {
  return (
    <Markdown rehypePlugins={[[rehypeSanitize, schema]]} components={components} skipHtml>
      {children}
    </Markdown>
  )
}
