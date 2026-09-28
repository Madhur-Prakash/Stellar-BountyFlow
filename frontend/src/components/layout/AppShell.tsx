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

function NavItems({ groups }: { groups: ShellNavGroup[] }) {
  const { setOpenMobile, isMobile } = useSidebar()
  const location = useLocation()
  return (
    <>
      {groups.map((g) => (
        <SidebarGroup key={g.label}>
          <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {g.items.map((item) => {
                const active = item.end
                  ? location.pathname === item.to
                  : location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)
                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      asChild
                      isActive={active}
                      tooltip={item.label}
                      className="h-8 font-medium text-sidebar-foreground data-active:text-sidebar-accent-foreground [&>svg]:text-muted-foreground data-active:[&>svg]:text-primary"
                    >
                      <NavLink to={item.to} end={item.end} onClick={() => isMobile && setOpenMobile(false)}>
                        <item.icon aria-hidden />
                        <span>{item.label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
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
        <Button asChild variant="ghost" size="icon" className="relative">
          <Link to="/app/notifications" aria-label={label}>
            <Bell />
            {count > 0 && (
              <span
                className="absolute top-1.5 right-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[0.625rem] font-semibold text-primary-foreground tabular-nums"
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
          <div className="truncate text-xs font-normal text-muted-foreground">@{me.username}</div>
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

/** Authenticated shell: shadcn Sidebar (Sheet on mobile) + top bar. The workspace keeps native scrolling. */
export function AppShell({
  groups,
  footer,
  areaLabel,
}: {
  groups: ShellNavGroup[]
  footer?: ReactNode
  areaLabel: string
}) {
  return (
    <SidebarProvider defaultOpen={sidebarStartsOpen()}>
      <SkipLink />
      <Sidebar collapsible="icon" aria-label={`${areaLabel} navigation`}>
        <SidebarHeader className="h-14 justify-center px-3">
          <Link to="/" className="rounded-md" aria-label="BountyFlow home">
            <Logo className="group-data-[collapsible=icon]:[&>span:last-child]:hidden" />
          </Link>
        </SidebarHeader>
        <SidebarContent>
          <NavItems groups={groups} />
        </SidebarContent>
        {footer && <SidebarFooter className="border-t border-sidebar-border">{footer}</SidebarFooter>}
      </Sidebar>
      <div className="flex min-h-dvh w-full min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/80 px-3 backdrop-blur-lg sm:px-4">
          <SidebarTrigger
            className="size-8 text-muted-foreground max-lg:size-10"
            aria-label="Toggle navigation"
          />
          <span aria-hidden className="hidden h-4 w-px bg-border lg:block" />
          <span className="hidden text-sm font-medium text-muted-foreground lg:inline">{areaLabel}</span>
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            <NetworkBadge compact />
            <NotificationsBell />
            <WalletButton className="hidden lg:inline-flex" />
            <UserMenu />
          </div>
        </header>
        {/* Below lg the header is too narrow for the wallet control (sidebar + badges), so it gets its own row. */}
        <div className={cn('flex justify-end border-b px-3 py-2 sm:px-4 lg:hidden')}>
          <WalletButton className="w-full sm:w-auto" />
        </div>
        <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 outline-none">
          <AnimatedOutlet className="mx-auto w-full max-w-384 px-4 py-6 sm:px-6 lg:px-8 lg:py-8" />
        </main>
      </div>
    </SidebarProvider>
  )
}
