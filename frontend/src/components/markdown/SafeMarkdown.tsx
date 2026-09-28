import type { ComponentProps } from 'react'
import Markdown, { type Components } from 'react-markdown'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'

import { cn } from '@/lib/utils'

/**
 * Renders untrusted Markdown safely:
 * - raw HTML is never parsed (react-markdown ignores it without rehype-raw),
 *   and rehype-sanitize strips anything outside a strict allow-list;
 * - links open in a new tab with rel="noopener noreferrer nofollow";
 * - only http(s)/mailto URLs survive; images are shown as links (no tracking pixels).
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

export function SafeMarkdown({
  children,
  className,
  ...rest
}: { children: string | null | undefined; className?: string } & Omit<ComponentProps<'div'>, 'children'>) {
  if (!children) return null
  return (
    <div
      {...rest}
      className={cn(
        'max-w-none text-[0.9375rem] leading-7 text-foreground/90',
        '[&_h1]:mt-8 [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold',
        '[&_h2]:mt-7 [&_h2]:mb-3 [&_h2]:text-lg [&_h2]:font-semibold',
        '[&_h3]:mt-6 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-semibold',
        '[&_li]:my-1 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:my-3 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6',
        '[&_blockquote]:my-4 [&_blockquote]:border-l-2 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground',
        '[&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em]',
        '[&_pre]:my-4 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:bg-surface [&_pre]:p-4 [&_pre_code]:bg-transparent [&_pre_code]:p-0',
        '[&_hr]:my-6 [&_td]:border-b [&_td]:px-3 [&_td]:py-2 [&_th]:border-b [&_th]:px-3 [&_th]:py-2 [&_th]:text-left',
        '[&>*:first-child]:mt-0',
        className,
      )}
    >
      <Markdown rehypePlugins={[[rehypeSanitize, schema]]} components={components} skipHtml>
        {children}
      </Markdown>
    </div>
  )
}
