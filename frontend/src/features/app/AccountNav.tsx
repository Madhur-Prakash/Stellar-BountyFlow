import { Bell, Laptop, SunMoon, UserRound, Wallet, type LucideIcon } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router'

import { scrollToAnchorWhenReady } from '@/lib/scroll'
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
    ],
  },
  {
    label: 'Settings',
    path: '/app/settings',
    sections: [
      { id: 'notifications', label: 'Notifications', icon: Bell },
      { id: 'sessions', label: 'Sessions', icon: Laptop },
      { id: 'appearance', label: 'Appearance', icon: SunMoon },
    ],
  },
]

/** Where a section's top must be (px from the viewport top) to count as the one being read. */
const READING_LINE = 120

/** The section currently being read: the last one whose top has passed the reading line. */
function useActiveSection(ids: string[]): string | undefined {
  const [active, setActive] = useState<string | undefined>(ids[0])
  const key = ids.join(',')
  useEffect(() => {
    const list = key.split(',')
    let raf = 0
    const update = () => {
      raf = 0
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
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      if (raf) cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [key])
  return active
}

/**
 * Profile and settings share one layout: a section nav on the left from lg up and the page's cards on the right.
 * Sections on the other page are ordinary links with a hash. Below lg the cards simply stack.
 */
export function AccountLayout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const group = GROUPS.find((g) => g.path === location.pathname) ?? GROUPS[0]!
  const active = useActiveSection(group.sections.map((s) => s.id))

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
              <p className="px-2.5 text-xs font-medium text-muted-foreground">{g.label}</p>
              <ul className="mt-1.5 space-y-0.5">
                {g.sections.map((s) => (
                  <li key={s.id}>
                    <Link
                      to={`${g.path}#${s.id}`}
                      aria-current={isActive(g, s) ? 'location' : undefined}
                      className={cn(
                        'flex h-8 items-center gap-2 rounded-md px-2.5 text-sm transition-colors',
                        isActive(g, s)
                          ? 'bg-muted font-medium text-foreground [&>svg]:text-primary'
                          : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
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
