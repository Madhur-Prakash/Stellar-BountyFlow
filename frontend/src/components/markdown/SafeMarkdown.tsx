import { lazy, Suspense, type ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** react-markdown and its plugins are a separate chunk; see MarkdownRenderer for the sanitising rules. */
const MarkdownRenderer = lazy(() => import('./MarkdownRenderer'))

/** Readable stand-in while the renderer loads: paragraphs of plain text with the Markdown syntax dropped. */
function PlainText({ text }: { text: string }) {
  const blocks = text
    .split(/\n\s*\n/)
    .map((block) =>
      block
        .replace(/^#{1,6}\s+/gm, '')
        .replace(/^\s*>\s?/gm, '')
        .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(/\*\*|__|`/g, '')
        .trim(),
    )
    .filter(Boolean)
  return (
    <div data-slot="markdown-fallback">
      {blocks.map((block, i) => (
        <p key={i} className="whitespace-pre-line">
          {block}
        </p>
      ))}
    </div>
  )
}

/** Renders untrusted Markdown safely (no raw HTML, sanitised output, hardened links, images shown as links). */
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
        '[&_h2]:mt-7 [&_h2]:mb-2.5 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-foreground',
        '[&_h3]:mt-6 [&_h3]:mb-2 [&_h3]:text-[0.9375rem] [&_h3]:font-semibold [&_h3]:text-foreground',
        '[&_li]:my-1 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:my-3 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6',
        '[&_blockquote]:my-4 [&_blockquote]:border-l-2 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground',
        '[&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em]',
        '[&_pre]:my-4 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:bg-surface [&_pre]:p-4 [&_pre_code]:bg-transparent [&_pre_code]:p-0',
        '[&_hr]:my-6 [&_td]:border-b [&_td]:px-3 [&_td]:py-2 [&_th]:border-b [&_th]:px-3 [&_th]:py-2 [&_th]:text-left',
        '[&>*:first-child]:mt-0 [&>[data-slot=markdown-fallback]>*:first-child]:mt-0',
        className,
      )}
    >
      <Suspense fallback={<PlainText text={children} />}>
        <MarkdownRenderer>{children}</MarkdownRenderer>
      </Suspense>
    </div>
  )
}
