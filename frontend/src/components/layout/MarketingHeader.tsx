import { Menu } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
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
import { useMe } from '@/lib/api/queries/auth'
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
  if (isPending) return <div className={cn('h-9', stacked ? 'w-full' : 'w-20')} aria-hidden />
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
    <Button asChild variant="ghost" className="rounded-full">
      <Link to="/login" onClick={onNavigate}>
        Sign in
      </Link>
    </Button>
  )
}

/** The mobile menu's links fade in one after another each time the sheet opens. */
function MobileNavList({ onNavigate }: { onNavigate: () => void }) {
  const firstLink = useRef<HTMLAnchorElement>(null)
  const onAnchor = useAnchorNavigation()

  useEffect(() => firstLink.current?.focus(), [])

  return (
    <ul className="space-y-0.5">
      {MOBILE_NAV.map((item, index) => (
        <li
          key={item.to}
          className="animate-in duration-300 ease-out fade-in-0 fill-mode-both slide-in-from-right-2"
          style={{ animationDelay: `${index * 35}ms` }}
        >
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

/** Sticky site header: logo, primary navigation, theme, account and the main action. */
export function MarketingHeader() {
  const [open, setOpen] = useState(false)
  // Transparent over the top of the page; a surface and a hairline once the page has scrolled.
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 8)
    update()
    window.addEventListener('scroll', update, { passive: true })
    return () => window.removeEventListener('scroll', update)
  }, [])

  return (
    <header
      data-scrolled={scrolled || undefined}
      className="sticky top-0 z-40 border-b border-transparent transition-[background-color,border-color] duration-300 data-scrolled:border-border data-scrolled:bg-background/80 data-scrolled:backdrop-blur-lg"
    >
      <div className="mx-auto flex h-16 max-w-384 items-center gap-3 px-4 sm:px-6 lg:px-8 2xl:px-12">
        <Link to="/" className="shrink-0 rounded-md" aria-label="BountyFlow home">
          <Logo />
        </Link>

        <nav aria-label="Primary" className="ml-auto hidden items-center gap-1 lg:flex">
          {MARKETING_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'rounded-full px-3 py-1.5 text-sm whitespace-nowrap transition-colors hover:text-foreground',
                  isActive ? 'text-foreground' : 'text-muted-foreground',
                  item.wideOnly && 'hidden xl:inline-flex',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5 lg:ml-3">
          <ThemeToggle className="hidden rounded-full sm:inline-flex" />
          <div className="hidden items-center gap-1.5 lg:flex">
            <AccountLinks />
            <Button asChild variant="inverse" className="rounded-full px-4">
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
