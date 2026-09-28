import { Menu } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, NavLink } from 'react-router'

import { Logo } from '@/components/brand/Logo'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { useAnchorNavigation } from '@/hooks/useAnchorNavigation'
import { motionAllowed } from '@/hooks/useReducedMotion'
import { useMe } from '@/lib/api/queries/auth'
import { gsap, ScrollTrigger, useGSAP } from '@/lib/gsap'
import { cn } from '@/lib/utils'

type NavItem = { label: string; to: string; wideOnly?: boolean }

const MARKETING_NAV: NavItem[] = [
  { label: 'Marketplace', to: '/bounties' },
  { label: 'How it works', to: '/how-it-works' },
  { label: 'Guide', to: '/guide' },
  { label: 'About', to: '/about', wideOnly: true },
]

const MOBILE_NAV: NavItem[] = [...MARKETING_NAV, { label: 'Escrow contract', to: '/#escrow' }]

function AccountLinks({ stacked = false, onNavigate }: { stacked?: boolean; onNavigate?: () => void }) {
  const { data: me, isPending } = useMe()
  if (isPending) return <div className={cn('h-10', stacked ? 'w-full' : 'w-20')} aria-hidden />
  if (me) {
    return (
      <Button asChild variant={stacked ? 'outline' : 'ghost'} className={cn(stacked && 'w-full')}>
        <Link to="/app" onClick={onNavigate}>
          <UserAvatar user={me} className="size-6" />
          Dashboard
        </Link>
      </Button>
    )
  }
  if (stacked) {
    return (
      <div className="grid grid-cols-2 gap-2">
        <Button asChild variant="outline">
          <Link to="/login" onClick={onNavigate}>
            Sign in
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/register" onClick={onNavigate}>
            Create account
          </Link>
        </Button>
      </div>
    )
  }
  return (
    <Button asChild variant="ghost">
      <Link to="/login" onClick={onNavigate}>
        Sign in
      </Link>
    </Button>
  )
}

/** The mobile menu's links slide in one after another each time the sheet opens. */
function MobileNavList({ onNavigate }: { onNavigate: () => void }) {
  const list = useRef<HTMLUListElement>(null)
  const firstLink = useRef<HTMLAnchorElement>(null)
  const onAnchor = useAnchorNavigation()

  useGSAP(
    () => {
      firstLink.current?.focus()
      if (!motionAllowed()) return
      gsap.from('li', { autoAlpha: 0, x: 12, duration: 0.35, stagger: 0.035, ease: 'bf-settle' })
    },
    { scope: list },
  )

  return (
    <ul ref={list} className="space-y-0.5">
      {MOBILE_NAV.map((item, index) => (
        <li key={item.to}>
          <Link
            ref={index === 0 ? firstLink : undefined}
            to={item.to}
            onClick={(e) => onAnchor(e, item.to, onNavigate)}
            className="flex min-h-11 items-center rounded-md px-3 text-[0.95rem] hover:bg-muted"
          >
            {item.label}
          </Link>
        </li>
      ))}
    </ul>
  )
}

/**
 * Fixed site header. It slides away while you scroll down through a page and comes back as soon as you scroll
 * up; it never hides near the top, under reduced motion, or while focus is inside it.
 */
export function MarketingHeader() {
  const [open, setOpen] = useState(false)
  const header = useRef<HTMLElement>(null)

  useGSAP(
    () => {
      const el = header.current
      if (!el) return
      let hidden = false
      const setHidden = (next: boolean) => {
        if (next === hidden) return
        hidden = next
        gsap.to(el, { yPercent: next ? -100 : 0, duration: 0.4, ease: 'bf-snap', overwrite: true })
      }
      const trigger = ScrollTrigger.create({
        start: 0,
        end: 'max',
        onUpdate: (self) => {
          const y = self.scroll()
          el.toggleAttribute('data-scrolled', y > 8)
          if (!motionAllowed()) return
          const keepVisible = y < 160 || self.direction < 0 || el.contains(document.activeElement)
          setHidden(!keepVisible)
        },
      })
      // Keyboard users tabbing into a hidden header bring it back.
      const onFocus = () => setHidden(false)
      el.addEventListener('focusin', onFocus)
      return () => {
        trigger.kill()
        el.removeEventListener('focusin', onFocus)
      }
    },
    { scope: header },
  )

  return (
    <header
      ref={header}
      className="fixed inset-x-0 top-0 z-40 border-b border-transparent bg-background/90 backdrop-blur-md transition-[border-color,box-shadow] duration-300 data-scrolled:border-border data-scrolled:shadow-[0_8px_24px_-18px_rgb(16_24_40/0.25)]"
    >
      <div className="mx-auto flex h-16 max-w-384 items-center gap-3 px-4 sm:px-6 lg:px-8 2xl:px-12">
        <Link to="/" className="shrink-0 rounded-md" aria-label="BountyFlow home">
          <Logo />
        </Link>

        <nav aria-label="Primary" className="ml-6 hidden items-center gap-1 lg:flex">
          {MARKETING_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'relative rounded-md px-3 py-2 text-[0.9375rem] whitespace-nowrap transition-colors hover:text-foreground',
                  'after:absolute after:inset-x-3 after:bottom-1 after:h-px after:origin-left after:scale-x-0 after:bg-foreground after:transition-transform after:duration-300 hover:after:scale-x-100',
                  isActive ? 'font-medium text-foreground after:scale-x-100' : 'text-muted-foreground',
                  item.wideOnly && 'hidden xl:inline-flex',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          <ThemeToggle className="hidden sm:inline-flex" />
          <div className="hidden items-center gap-1.5 lg:flex">
            <AccountLinks />
            <Button asChild>
              <Link to="/app/bounties/create">Post a bounty</Link>
            </Button>
          </div>

          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu">
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent
              side="right"
              className="w-[88vw] max-w-sm gap-0 p-0"
              aria-describedby="mobile-nav-desc"
              // Radix skips links when auto-focusing, which would land on the network label (and open its
              // tooltip, so Escape only closed the tooltip). MobileNavList focuses the first link instead.
              onOpenAutoFocus={(e) => e.preventDefault()}
            >
              <SheetHeader className="border-b px-5 py-4">
                <SheetTitle>Menu</SheetTitle>
                <SheetDescription id="mobile-nav-desc" className="sr-only">
                  Site navigation and account links
                </SheetDescription>
              </SheetHeader>
              <nav aria-label="Mobile" className="flex-1 overflow-y-auto px-3 py-4">
                <MobileNavList onNavigate={() => setOpen(false)} />
                <Separator className="my-4" />
                <div className="space-y-2 px-1">
                  <Button asChild className="w-full">
                    <Link to="/app/bounties/create" onClick={() => setOpen(false)}>
                      Post a bounty
                    </Link>
                  </Button>
                  <AccountLinks stacked onNavigate={() => setOpen(false)} />
                </div>
              </nav>
              <div className="flex items-center justify-between border-t px-5 py-3 text-sm text-muted-foreground">
                Theme
                <ThemeToggle />
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}
