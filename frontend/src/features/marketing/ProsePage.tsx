import { useEffect, useRef, useState, type ReactNode } from 'react'

import { PageContainer } from '@/components/layout/PageContainer'
import { motionAllowed } from '@/hooks/useReducedMotion'
import { scrollToAnchor } from '@/lib/scroll'
import { cn } from '@/lib/utils'

export type ProseSection = { id: string; title: string; body: ReactNode }

/**
 * Long-form page (guide, legal): a table of contents that follows your position on desktop, the reading column,
 * and an optional rail on wide screens (`aside`) for related actions.
 */
export function ProsePage({
  title,
  intro,
  sections,
  notice,
  updated,
  aside,
}: {
  /** Kept for call-site compatibility; section labels above headings are not rendered. */
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
    <PageContainer className="py-14 sm:py-20">
      <header className="max-w-4xl">
        <h1 className="font-display text-[2.125rem] leading-[1.1] sm:text-[2.5rem]">{title}</h1>
        <div className="mt-4 max-w-3xl text-[1.0625rem] leading-relaxed text-muted-foreground">{intro}</div>
        {updated && <p className="mt-3 text-sm text-muted-foreground">Last updated {updated}</p>}
        {notice && <div className="mt-6">{notice}</div>}
      </header>

      <div
        ref={body}
        className={cn(
          'mt-14 grid gap-12 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-16',
          aside && 'xl:grid-cols-[15rem_minmax(0,1fr)_17rem]',
        )}
      >
        <nav aria-label="On this page" className="hidden lg:block">
          <div className="sticky top-24">
            <h2 className="text-sm font-medium text-muted-foreground">On this page</h2>
            <ul className="mt-3 space-y-0.5 border-l">
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
                      '-ml-px block rounded-r-md border-l-2 py-1.5 pl-4 text-sm transition-colors duration-300',
                      active === s.id
                        ? 'border-primary bg-primary/[0.06] font-medium text-primary-emphasis'
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

        <div className="max-w-184 space-y-16">
          {sections.map((s) => (
            <section key={s.id} id={s.id} aria-labelledby={`${s.id}-h`} className="scroll-mt-24">
              <h2 id={`${s.id}-h`} className="font-display text-[1.375rem] leading-tight">
                {s.title}
              </h2>
              <div className="mt-3 space-y-4 text-[0.9375rem] leading-7 text-foreground/85 [&_a]:text-primary-emphasis [&_a]:underline [&_a]:underline-offset-4 [&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em] [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:pl-6">
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
