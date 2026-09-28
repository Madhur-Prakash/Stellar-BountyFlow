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
  PlusCircle,
  Search,
  Settings2,
  ShieldCheck,
  User,
} from 'lucide-react'
import { Link } from 'react-router'

import { UserAvatar } from '@/components/common/UserAvatar'
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'
import { useMe } from '@/lib/api/queries/auth'
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
    ],
  },
]

/** Who is signed in, at the foot of the sidebar (just the avatar on the icon rail). */
function SignedInAs() {
  const { data: me } = useMe()
  if (!me) return null
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton asChild size="lg" tooltip={me.display_name}>
          <Link to="/app/profile" aria-label={`${me.display_name}, profile`}>
            <UserAvatar user={me} className="size-8" />
            <span className="grid min-w-0 flex-1 leading-tight">
              <span className="truncate text-sm font-medium text-sidebar-accent-foreground">
                {me.display_name}
              </span>
              <span className="truncate text-xs text-muted-foreground">{me.email}</span>
            </span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

export function AppLayout() {
  const { data: me } = useMe()
  const staff = hasPermission(me, STAFF_PERMISSION)
  const groups: ShellNavGroup[] = staff
    ? [...APP_NAV, { label: 'Staff', items: [{ label: 'Admin console', to: '/admin', icon: ShieldCheck }] }]
    : APP_NAV
  return <AppShell areaLabel="Workspace" groups={groups} footer={<SignedInAs />} />
}
