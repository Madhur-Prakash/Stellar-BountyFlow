import {
  ArrowLeftRight,
  Bell,
  Bookmark,
  BriefcaseBusiness,
  ChartNoAxesCombined,
  CircleDollarSign,
  FileCheck2,
  GitPullRequest,
  LayoutDashboard,
  LockKeyhole,
  PlusCircle,
  Search,
  Settings2,
  ShieldCheck,
  User,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { UserAvatar } from '@/components/common/UserAvatar'
import { LegalNotice } from '@/features/app/privacy/LegalGate'
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from '@/components/ui/sidebar'
import { useMe } from '@/lib/api/queries/auth'
import { useUnreadNotificationCount } from '@/lib/api/queries/notifications'
import { hasPermission, STAFF_PERMISSION } from '@/lib/permissions'

import { AppShell, type ShellNavGroup } from './AppShell'

const APP_NAV: ShellNavGroup[] = [
  {
    label: 'Overview',
    items: [
      { label: 'Dashboard', to: '/app', icon: LayoutDashboard, end: true },
      { label: 'Analytics', to: '/app/analytics', icon: ChartNoAxesCombined },
      { label: 'Notifications', to: '/app/notifications', icon: Bell },
    ],
  },
  {
    label: 'Requester',
    items: [
      { label: 'My bounties', to: '/app/bounties', icon: BriefcaseBusiness, end: true },
      { label: 'Post a bounty', to: '/app/bounties/create', icon: PlusCircle },
    ],
  },
  {
    label: 'Contributor',
    items: [
      { label: 'Find work', to: '/bounties', icon: Search },
      { label: 'Applications', to: '/app/applications', icon: GitPullRequest },
      { label: 'Submissions', to: '/app/submissions', icon: FileCheck2 },
      { label: 'Saved', to: '/app/saved', icon: Bookmark },
    ],
  },
  {
    label: 'Money',
    items: [
      { label: 'Payments', to: '/app/payments', icon: CircleDollarSign },
      { label: 'Transactions', to: '/app/transactions', icon: ArrowLeftRight },
    ],
  },
  {
    label: 'Account',
    items: [
      { label: 'Profile', to: '/app/profile', icon: User },
      { label: 'Settings', to: '/app/settings', icon: Settings2 },
      { label: 'Privacy', to: '/app/privacy', icon: LockKeyhole },
    ],
  },
]

/**
 * Search the marketplace from anywhere in the workspace: opens /bounties with the query. Left out of the mobile
 * navigation sheet, where it would take the sheet's initial focus and open the on-screen keyboard (the
 * marketplace has its own search).
 */
function MarketplaceSearch() {
  const navigate = useNavigate()
  const { isMobile } = useSidebar()
  const [q, setQ] = useState('')
  if (isMobile) return null
  return (
    <form
      role="search"
      aria-label="Marketplace"
      className="relative"
      onSubmit={(e) => {
        e.preventDefault()
        const term = q.trim()
        navigate(term ? `/bounties?q=${encodeURIComponent(term)}` : '/bounties')
        setQ('')
      }}
    >
      <Search
        className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Search the marketplace"
        placeholder="Search bounties"
        enterKeyHint="search"
        className="h-8 w-full min-w-0 rounded-md border border-sidebar-border bg-sidebar-accent/60 pr-2 pl-8 text-[0.8125rem] text-foreground transition-colors outline-none placeholder:text-muted-foreground hover:bg-sidebar-accent focus-visible:border-ring focus-visible:bg-background focus-visible:ring-3 focus-visible:ring-ring/25 [&::-webkit-search-cancel-button]:hidden"
      />
    </form>
  )
}

/** Who is signed in, at the foot of the sidebar (just the avatar on the icon rail). */
function SignedInAs() {
  const { data: me } = useMe()
  if (!me) return null
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton asChild size="lg" tooltip={me.display_name} className="h-11 px-2">
          <Link to="/app/profile" aria-label={`${me.display_name}, profile`}>
            <UserAvatar user={me} className="size-7" />
            <span className="grid min-w-0 flex-1 leading-tight">
              <span className="truncate text-[0.8125rem] font-medium text-foreground">{me.display_name}</span>
              <span className="truncate font-mono text-[0.6875rem] text-muted-foreground">{me.email}</span>
            </span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

export function AppLayout() {
  const { data: me } = useMe()
  const { count: unread } = useUnreadNotificationCount(!!me)
  const staff = hasPermission(me, STAFF_PERMISSION)
  const nav = APP_NAV.map((g) => ({
    ...g,
    items: g.items.map((item) => (item.to === '/app/notifications' ? { ...item, count: unread } : item)),
  }))
  const groups: ShellNavGroup[] = staff
    ? [...nav, { label: 'Staff', items: [{ label: 'Admin console', to: '/admin', icon: ShieldCheck }] }]
    : nav
  return (
    <AppShell
      areaLabel="Workspace"
      groups={groups}
      search={<MarketplaceSearch />}
      footer={<SignedInAs />}
      notice={<LegalNotice />}
    />
  )
}
