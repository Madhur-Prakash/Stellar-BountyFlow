import { Bell, LogOut, Moon, Settings2, Sun, User, UserRound } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Logo } from '@/components/brand/Logo'
import { NetworkBadge } from '@/components/chain/NetworkBadge'
import { WalletButton } from '@/components/chain/WalletButton'
import { MAIN_CONTENT_ID, SkipLink } from '@/components/common/SkipLink'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { errorMessage } from '@/lib/api/client'
import { useLogout, useMe } from '@/lib/api/queries/auth'
import { useUnreadNotificationCount } from '@/lib/api/queries/notifications'
import { originOf, switchTheme } from '@/lib/theme-transition'
import { cn } from '@/lib/utils'
import { useAuthUi } from '@/stores/auth-ui'
import { useUiPrefs } from '@/stores/ui-prefs'

import { AnimatedOutlet } from './AnimatedOutlet'

export type ShellNavItem = { label: string; to: string; icon: LucideIcon; end?: boolean }
export type ShellNavGroup = { label: string; items: ShellNavItem[] }

const isActive = (item: ShellNavItem, pathname: string) =>
  item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(`${item.to}/`)

/**
 * The nav item a page belongs to, for the title in the top bar: the deepest item whose path the current one
 * starts with (so /app/bounties/:id is under "My bounties"). The area's root item only matches itself.
 */
function currentSection(groups: ShellNavGroup[], pathname: string): string | null {
  let best: ShellNavItem | null = null
  for (const item of groups.flatMap((g) => g.items)) {
    const root = item.to.split('/').filter(Boolean).length <= 1
    const hit = pathname === item.to || (!root && pathname.startsWith(`${item.to}/`))
    if (hit && (!best || item.to.length > best.to.length)) best = item
  }
  return best?.label ?? null
}

/** Sidebar rows: compact, quiet until hovered; the current page is a filled row. */
export const SHELL_ROW =
  'h-8 gap-2.5 rounded-md px-2 text-[0.84375rem] font-normal text-foreground/80 transition-colors hover:bg-sidebar-accent/70 hover:text-foreground data-active:bg-sidebar-accent data-active:font-medium data-active:text-foreground light:data-active:shadow-[inset_0_0_0_1px_var(--sidebar-border)] [&>svg]:text-muted-foreground hover:[&>svg]:text-foreground data-active:[&>svg]:text-primary-emphasis'

function NavItems({ groups }: { groups: ShellNavGroup[] }) {
  const { setOpenMobile, isMobile } = useSidebar()
  const location = useLocation()
  return (
    <>
      {groups.map((g) => (
        <SidebarGroup key={g.label} className="px-2 py-1.5">
          <SidebarGroupLabel className="h-7 px-2 font-mono text-[0.75rem] font-normal tracking-[0.01em] text-muted-foreground">
            {g.label}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-px">
              {g.items.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item, location.pathname)}
                    tooltip={item.label}
                    className={SHELL_ROW}
                  >
                    <NavLink to={item.to} end={item.end} onClick={() => isMobile && setOpenMobile(false)}>
                      <item.icon aria-hidden />
                      <span>{item.label}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      ))}
    </>
  )
}

function NotificationsBell() {
  const { data: me } = useMe()
  const { count } = useUnreadNotificationCount(!!me)
  const label = count > 0 ? `Notifications, ${count} unread` : 'Notifications'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button asChild variant="ghost" size="icon" className="relative text-muted-foreground hover:text-foreground">
          <Link to="/app/notifications" aria-label={label}>
            <Bell />
            {count > 0 && (
              <span
                className="absolute top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 font-mono text-[0.625rem] font-medium text-primary-foreground tabular-nums ring-2 ring-background"
                aria-hidden
              >
                {count > 99 ? '99+' : count}
              </span>
            )}
          </Link>
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function UserMenu() {
  const { data: me } = useMe()
  const logout = useLogout()
  const navigate = useNavigate()
  const theme = useUiPrefs((s) => s.theme)
  if (!me) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Account menu" className="rounded-full">
          <UserAvatar user={me} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel>
          <div className="truncate font-medium">{me.display_name}</div>
          <div className="truncate font-mono text-xs font-normal text-muted-foreground">@{me.username}</div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/app/profile">
            <User /> Edit profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to={`/u/${me.username}`}>
            <UserRound /> Public profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/app/settings">
            <Settings2 /> Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() =>
            switchTheme(
              theme === 'dark' ? 'light' : 'dark',
              originOf(document.querySelector('[aria-label="Account menu"]')),
            )
          }
        >
          {theme === 'dark' ? <Sun /> : <Moon />} {theme === 'dark' ? 'Light theme' : 'Dark theme'}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onSelect={() => {
            // Tell the route guard this is a deliberate sign-out, so clearing the session
            // sends the user home rather than to /login?next=… for the page they were on.
            useAuthUi.getState().setSigningOut(true)
            logout.mutate(undefined, {
              onError: (e) => toast.error(errorMessage(e)),
              onSettled: () => void navigate('/', { replace: true }),
            })
          }}
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * The sidebar starts expanded only where there is room for it next to the
 * content (≥ 1024px); tablets start with the icon rail. Mobile always uses the sheet.
 */
function sidebarStartsOpen(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true
  return window.matchMedia('(min-width: 1024px)').matches
}

/**
 * Authenticated shell: shadcn Sidebar (Sheet on mobile) + top bar. The workspace keeps native scrolling.
 * `search` sits under the logo in the expanded sidebar (hidden on the icon rail).
 */
export function AppShell({
  groups,
  footer,
  areaLabel,
  search,
}: {
  groups: ShellNavGroup[]
  footer?: ReactNode
  areaLabel: string
  search?: ReactNode
}) {
  const { pathname } = useLocation()
  const section = currentSection(groups, pathname)
  return (
    <SidebarProvider defaultOpen={sidebarStartsOpen()}>
      <SkipLink />
      <Sidebar collapsible="icon" aria-label={`${areaLabel} navigation`}>
        <SidebarHeader className="h-14 justify-center px-3.5 group-data-[collapsible=icon]:px-2">
          <Link to="/" className="rounded-md" aria-label="BountyFlow home">
            <Logo
              className="gap-2.5 group-data-[collapsible=icon]:[&>span:last-child]:hidden"
              markClassName="size-6.5"
            />
          </Link>
        </SidebarHeader>
        <SidebarContent className="pb-2">
          {search && <div className="px-3 pt-1 pb-2 group-data-[collapsible=icon]:hidden">{search}</div>}
          <NavItems groups={groups} />
        </SidebarContent>
        {footer && (
          <SidebarFooter className="border-t border-sidebar-border px-2 py-2">{footer}</SidebarFooter>
        )}
      </Sidebar>
      <div className="flex min-h-dvh w-full min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur-lg sm:px-4">
          <SidebarTrigger
            className="size-8 text-muted-foreground hover:text-foreground max-lg:size-10"
            aria-label="Toggle navigation"
          />
          <span aria-hidden className="hidden h-4 w-px bg-border md:block" />
          <div className="flex min-w-0 items-center gap-2.5 pl-1">
            <span className={cn('label-mono shrink-0 text-[0.75rem]', section && 'hidden md:inline')}>
              {areaLabel}
            </span>
            {section && (
              <>
                <span aria-hidden className="hidden h-3.5 w-px rotate-18 bg-border md:block" />
                <span className="truncate text-sm font-medium text-foreground">{section}</span>
              </>
            )}
          </div>
          <div className="ml-auto flex items-center gap-1 sm:gap-1.5">
            <NetworkBadge compact />
            <NotificationsBell />
            <WalletButton className="hidden lg:inline-flex" />
            <UserMenu />
          </div>
        </header>
        {/* Below lg the header is too narrow for the wallet control (sidebar + badges), so it gets its own row. */}
        <div className="flex justify-end border-b bg-surface/50 px-3 py-2 sm:px-4 lg:hidden">
          <WalletButton className="w-full sm:w-auto" />
        </div>
        <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 outline-none">
          <AnimatedOutlet className="mx-auto w-full max-w-384 px-4 py-6 sm:px-6 lg:px-8 lg:py-8" />
        </main>
      </div>
    </SidebarProvider>
  )
}
