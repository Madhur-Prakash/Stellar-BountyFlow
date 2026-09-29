import {
  Bell,
  Coins,
  FileDown,
  GitBranch,
  Laptop,
  Scale,
  ShieldCheck,
  SunMoon,
  UserRound,
  UserX,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router'

import { scrollToAnchor, scrollToAnchorWhenReady } from '@/lib/scroll'
import { cn } from '@/lib/utils'

type Section = { id: string; label: string; icon: LucideIcon }
type Group = { label: string; path: string; sections: Section[] }

const GROUPS: Group[] = [
  {
    label: 'Profile',
    path: '/app/profile',
    sections: [
      { id: 'details', label: 'Public details', icon: UserRound },
      { id: 'wallets', label: 'Wallets', icon: Wallet },
      { id: 'assets', label: 'Assets', icon: Coins },
      { id: 'reputation', label: 'Completed on-chain', icon: ShieldCheck },
    ],
  },
  {
    label: 'Settings',
    path: '/app/settings',
    sections: [
      { id: 'notifications', label: 'Notifications', icon: Bell },
      { id: 'github', label: 'GitHub', icon: GitBranch },
      { id: 'sessions', label: 'Sessions', icon: Laptop },
      { id: 'appearance', label: 'Appearance', icon: SunMoon },
    ],
  },
  {
    label: 'Privacy',
    path: '/app/privacy',
    sections: [
      { id: 'export', label: 'Your data', icon: FileDown },
      { id: 'legal', label: 'Terms and privacy', icon: Scale },
      { id: 'delete', label: 'Delete account', icon: UserX },
    ],
  },
]

/** Where a section's top must be (px from the viewport top) to count as the one being read. */
const READING_LINE = 120

/**
 * The section currently being read: the last one whose top has passed the reading line, or the final section
 * once the page is scrolled to the end (the last sections are often too short to reach the line, so without
 * that they could never highlight).
 *
 * **A clicked entry is pinned**, and stays chosen until the reader scrolls of their own accord. A timer is not
 * enough here: these pages are short — the whole of Privacy scrolls about 100px — so "Delete account" is still
 * below the line even at the very bottom, and the moment a timed hold expired the highlight jumped back to the
 * section above it. Pinning also stops the highlight flickering through everything the page passes on the way.
 *
 * Only real input clears the pin (wheel, touch, or a scrolling key). Listening for `scroll` would not do: the
 * smooth scroll the click itself starts fires exactly that event.
 */
function useActiveSection(ids: string[]): [string | undefined, (id: string) => void] {
  const [active, setActive] = useState<string | undefined>(ids[0])
  const pinned = useRef<string | null>(null)
  const recheck = useRef<() => void>(() => {})
  const key = ids.join(',')

  useEffect(() => {
    const list = key.split(',')
    let raf = 0
    const update = () => {
      raf = 0
      if (pinned.current) return
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
      let current = list[0]
      for (const id of list) {
        const el = document.getElementById(id)
        if (el && el.getBoundingClientRect().top <= READING_LINE) current = id
      }
      if (atBottom && window.scrollY > 0) current = list[list.length - 1]
      setActive(current)
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }
    const release = () => {
      if (!pinned.current) return
      pinned.current = null
      onScroll()
    }
    const onKey = (e: KeyboardEvent) => {
      if (/^(Arrow|Page)|^(Home|End|Space)$/.test(e.key)) release()
    }
    recheck.current = onScroll
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    window.addEventListener('wheel', release, { passive: true })
    window.addEventListener('touchstart', release, { passive: true })
    window.addEventListener('keydown', onKey)
    return () => {
      if (raf) cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      window.removeEventListener('wheel', release)
      window.removeEventListener('touchstart', release)
      window.removeEventListener('keydown', onKey)
    }
  }, [key])

  /** Called on click: choose the entry and keep it until the reader scrolls. */
  const choose = (id: string) => {
    pinned.current = id
    setActive(id)
  }

  return [active, choose]
}

/**
 * Profile and settings share one layout: a section nav on the left from lg up and the page's cards on the right.
 * Sections on the other page are ordinary links with a hash. Below lg the cards simply stack.
 */
export function AccountLayout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const group = GROUPS.find((g) => g.path === location.pathname) ?? GROUPS[0]!
  const [active, choose] = useActiveSection(group.sections.map((s) => s.id))

  // Arriving at "#section" (from the nav or another page): scroll once the target has rendered and settled.
  useEffect(() => {
    if (!location.hash) return
    return scrollToAnchorWhenReady(location.hash)
  }, [location.key, location.hash])

  const isActive = (g: Group, s: Section) => g.path === location.pathname && active === s.id

  return (
    <div className="grid lg:grid-cols-[12.5rem_minmax(0,1fr)] lg:gap-10">
      <nav aria-label="Account" className="hidden min-w-0 lg:sticky lg:top-20 lg:block lg:self-start">
        <div className="space-y-5">
          {GROUPS.map((g) => (
            <div key={g.path}>
              <p className="label-mono px-2.5 text-[0.75rem]">{g.label}</p>
              <ul className="mt-1.5 space-y-px">
                {g.sections.map((s) => (
                  <li key={s.id}>
                    <Link
                      to={`${g.path}#${s.id}`}
                      aria-current={isActive(g, s) ? 'location' : undefined}
                      onClick={(e) => {
                        // Same page: scroll to the section rather than letting the router re-render, so a
                        // second click on the same entry still works and the choice stays highlighted.
                        if (g.path !== location.pathname) return
                        e.preventDefault()
                        choose(s.id)
                        scrollToAnchor(`#${s.id}`)
                        window.history.replaceState(null, '', `${g.path}#${s.id}`)
                      }}
                      className={cn(
                        'flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[0.84375rem] transition-colors [&>svg]:text-muted-foreground',
                        isActive(g, s)
                          ? 'bg-muted font-medium text-foreground shadow-[inset_0_0_0_1px_var(--border)] dark:shadow-none [&>svg]:text-primary-emphasis'
                          : 'text-foreground/80 hover:bg-muted/60 hover:text-foreground',
                      )}
                    >
                      <s.icon className="size-4 shrink-0" aria-hidden />
                      {s.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </nav>
      <div className="min-w-0 space-y-6 lg:max-w-3xl">{children}</div>
    </div>
  )
}
