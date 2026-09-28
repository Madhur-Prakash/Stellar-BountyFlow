import { useEffect, useRef, useState, type ReactNode } from 'react'

import { PageContainer } from '@/components/layout/PageContainer'
import { motionAllowed } from '@/hooks/useReducedMotion'
import { scrollToAnchor } from '@/lib/scroll'
import { cn } from '@/lib/utils'

export type ProseSection = { id: string; title: string; body: ReactNode }

/**
 * Long-form page (guide, legal) laid out like documentation: a large light title with a small mono label above it,
 * a table of contents that follows your position on desktop, the reading column, and an optional rail on wide
 * screens (`aside`) for related actions.
 */
export function ProsePage({
  eyebrow,
  title,
  intro,
  sections,
  notice,
  updated,
  aside,
}: {
  /** Small mono label above the title ("Guide", "Legal"). */
  eyebrow?: string
  title: string
  intro: ReactNode
  sections: ProseSection[]
  notice?: ReactNode
  updated?: string
  aside?: ReactNode
}) {
  const body = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(() => {
    const hash = typeof window === 'undefined' ? '' : decodeURIComponent(window.location.hash.slice(1))
    return sections.some((s) => s.id === hash) ? hash : sections[0]?.id
  })
  // After a click in the contents, keep that entry highlighted while the page glides to it, then re-read positions.
  const holdUntil = useRef(0)
  const recheck = useRef<() => void>(() => {})

  // The contents highlight the section being read: the last one whose top has passed 30% of the viewport, or
  // the last section once the page is scrolled to the end. Positions are read on every scroll (not cached), so
  // this stays right after content above changes height or the smooth-scroll engine changes.
  useEffect(() => {
    const root = body.current
    if (!root) return
    const nodes = Array.from(root.querySelectorAll<HTMLElement>('section[id]'))
    if (nodes.length === 0) return
    let frame = 0
    const update = () => {
      frame = 0
      if (performance.now() < holdUntil.current) return
      const line = window.innerHeight * 0.3
      const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4
      let current = nodes[0].id
      for (const node of nodes) if (node.getBoundingClientRect().top <= line) current = node.id
      if (atEnd) current = nodes[nodes.length - 1].id
      setActive(current)
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    recheck.current = schedule
    update()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
    }
  }, [sections])

  return (
    <PageContainer className="pt-14 pb-20 sm:pt-24 sm:pb-28">
      <header className="max-w-4xl">
        {eyebrow && <p className="label-mono">{eyebrow}</p>}
        <h1
          className={cn(
            'font-display text-[2.5rem] leading-[1.04] font-normal tracking-[-0.03em] sm:text-[3.5rem] lg:text-[4rem]',
            eyebrow && 'mt-4',
          )}
        >
          {title}
        </h1>
        <div className="mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground sm:mt-6 sm:text-xl sm:leading-[1.6]">
          {intro}
        </div>
        {updated && <p className="label-mono mt-6">Last updated {updated}</p>}
        {notice && <div className="mt-8 max-w-2xl">{notice}</div>}
      </header>

      <div
        ref={body}
        className={cn(
          'mt-14 grid gap-12 border-t pt-12 sm:mt-20 sm:pt-14 lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-16',
          aside && 'xl:grid-cols-[14rem_minmax(0,1fr)_16rem]',
        )}
      >
        <nav aria-label="On this page" className="hidden lg:block">
          <div className="sticky top-24">
            <h2 className="label-mono">On this page</h2>
            <ul className="mt-4 border-l">
              {sections.map((s) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    aria-current={active === s.id ? 'location' : undefined}
                    onClick={(e) => {
                      e.preventDefault()
                      const hold = motionAllowed() ? 1300 : 60
                      holdUntil.current = performance.now() + hold
                      window.setTimeout(() => recheck.current(), hold + 20)
                      setActive(s.id)
                      scrollToAnchor(s.id)
                      window.history.replaceState(null, '', `#${s.id}`)
                    }}
                    className={cn(
                      '-ml-px block border-l py-1.5 pl-4 text-sm transition-colors duration-300',
                      active === s.id
                        ? 'border-foreground font-medium text-foreground'
                        : 'border-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground',
                    )}
                  >
                    {s.title}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </nav>

        <div className="max-w-176 divide-y">
          {sections.map((s) => (
            <section
              key={s.id}
              id={s.id}
              aria-labelledby={`${s.id}-h`}
              className="scroll-mt-24 py-10 first:pt-0 last:pb-0 sm:py-12"
            >
              <h2
                id={`${s.id}-h`}
                className="font-display text-[1.5rem] leading-tight tracking-[-0.02em] sm:text-[1.75rem]"
              >
                {s.title}
              </h2>
              <div className="mt-4 space-y-4 text-base leading-7 text-foreground/80 sm:leading-[1.8] [&_a]:text-primary-emphasis [&_a]:underline [&_a]:decoration-primary-emphasis/40 [&_a]:underline-offset-4 [&_a:hover]:decoration-primary-emphasis [&_code]:rounded-[4px] [&_code]:border [&_code]:bg-surface [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em] [&_code]:text-foreground [&_li]:my-1.5 [&_li]:pl-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_strong]:font-medium [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:pl-6 [&_li::marker]:text-muted-foreground">
                {s.body}
              </div>
            </section>
          ))}
        </div>

        {aside && (
          <aside className="hidden xl:block">
            <div className="sticky top-24">{aside}</div>
          </aside>
        )}
      </div>
    </PageContainer>
  )
}
