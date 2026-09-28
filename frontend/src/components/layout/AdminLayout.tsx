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

import { Button } from '@/components/ui/button'

import { AppShell, type ShellNavGroup } from './AppShell'

const ADMIN_NAV: ShellNavGroup[] = [
  {
    label: 'Admin',
    items: [
      { label: 'Overview', to: '/admin', icon: LayoutDashboard, end: true },
      { label: 'Users', to: '/admin/users', icon: Users },
      { label: 'Bounties', to: '/admin/bounties', icon: BriefcaseBusiness },
      { label: 'Reports', to: '/admin/reports', icon: Flag },
      { label: 'Disputes', to: '/admin/disputes', icon: Scale },
      { label: 'Transactions', to: '/admin/transactions', icon: ArrowLeftRight },
      { label: 'Audit logs', to: '/admin/audit-logs', icon: ScrollText },
    ],
  },
]

export function AdminLayout() {
  return (
    <AppShell
      areaLabel="Admin console"
      groups={ADMIN_NAV}
      footer={
        <Button asChild variant="ghost" className="justify-start group-data-[collapsible=icon]:hidden">
          <Link to="/app">
            <ArrowLeft /> Back to workspace
          </Link>
        </Button>
      }
    />
  )
}
