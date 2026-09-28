import {
  ArrowLeft,
  ArrowLeftRight,
  BriefcaseBusiness,
  Flag,
  LayoutDashboard,
  ScrollText,
  Scale,
  Users,
} from 'lucide-react'
import { Link } from 'react-router'

import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'
import { useMe } from '@/lib/api/queries/auth'
import type { Permission } from '@/lib/api/types'
import { hasPermission } from '@/lib/permissions'

import { AppShell, SHELL_ROW, type ShellNavGroup, type ShellNavItem } from './AppShell'

/** Each section is listed only for staff who hold the permission its API needs. */
const ADMIN_NAV: (ShellNavItem & { permission?: Permission })[] = [
  { label: 'Overview', to: '/admin', icon: LayoutDashboard, end: true },
  { label: 'Users', to: '/admin/users', icon: Users, permission: 'user:view_all' },
  { label: 'Bounties', to: '/admin/bounties', icon: BriefcaseBusiness, permission: 'bounty:view_all' },
  { label: 'Reports', to: '/admin/reports', icon: Flag, permission: 'report:review' },
  { label: 'Disputes', to: '/admin/disputes', icon: Scale, permission: 'dispute:view_all' },
  {
    label: 'Transactions',
    to: '/admin/transactions',
    icon: ArrowLeftRight,
    permission: 'transaction:view_all',
  },
  { label: 'Audit logs', to: '/admin/audit-logs', icon: ScrollText, permission: 'audit:read' },
]

export function AdminLayout() {
  const { data: me } = useMe()
  const groups: ShellNavGroup[] = [
    {
      label: 'Admin',
      items: ADMIN_NAV.filter((item) => !item.permission || hasPermission(me, item.permission)).map(
        ({ permission: _permission, ...item }) => item,
      ),
    },
  ]
  return (
    <AppShell
      areaLabel="Admin console"
      groups={groups}
      footer={
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="Back to workspace" className={SHELL_ROW}>
              <Link to="/app">
                <ArrowLeft aria-hidden />
                <span>Back to workspace</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      }
    />
  )
}
