import { MailCheck, MailWarning, UserCheck, Users, UserX } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useDebounce } from '@/hooks/useDebounce'
import { errorMessage } from '@/lib/api/client'
import { useAdminUpdateUser, useAdminUsers } from '@/lib/api/queries/admin'
import { useMe } from '@/lib/api/queries/auth'
import { ROLES, type AdminUser, type Role } from '@/lib/api/types'
import { hasPermission } from '@/lib/permissions'

import {
  AdminTable,
  ConfirmDialog,
  DateCell,
  FilterSelect,
  PagedResults,
  RoleBadge,
  SearchField,
  UserCell,
  type AdminColumn,
} from './admin-shared'
import { ADMIN_PAGE_SIZE, ROLE_LABELS, scrollToTop, useFilteredPage } from './admin-utils'

export default function AdminUsersPage() {
  const { data: me } = useMe()
  const canAssignRole = hasPermission(me, 'user:assign_role')
  const canManage = hasPermission(me, 'user:manage')

  const [search, setSearch] = useState('')
  const q = useDebounce(search.trim(), 300)
  const [role, setRole] = useState<Role | undefined>(undefined)
  const [page, setPage] = useFilteredPage(`${q}|${role ?? ''}`)
  const query = useAdminUsers({ q: q || undefined, role, page, page_size: ADMIN_PAGE_SIZE })

  const update = useAdminUpdateUser()
  const pendingId = update.isPending ? update.variables?.id : undefined

  // Suspend / reactivate confirmation. The target is kept while the dialog animates closed.
  const [statusTarget, setStatusTarget] = useState<AdminUser | null>(null)
  const [statusOpen, setStatusOpen] = useState(false)

  const changeRole = (user: AdminUser, next: Role) => {
    if (next === user.role) return
    update.mutate(
      { id: user.id, body: { role: next } },
      {
        onSuccess: (updated) =>
          toast.success(`Role for @${updated.username} changed to ${ROLE_LABELS[updated.role]}.`),
        onError: (e) => toast.error(errorMessage(e)),
      },
    )
  }

  const confirmStatus = () => {
    if (!statusTarget) return
    const nextActive = !statusTarget.is_active
    update.mutate(
      { id: statusTarget.id, body: { is_active: nextActive } },
      {
        onSuccess: (updated) => {
          toast.success(
            nextActive
              ? `@${updated.username} has been reactivated.`
              : `@${updated.username} has been suspended and signed out of every session.`,
          )
          setStatusOpen(false)
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    )
  }

  const columns: AdminColumn<AdminUser>[] = [
    {
      key: 'user',
      header: 'User',
      mobile: 'title',
      cell: (u) => (
        <span className="inline-flex max-w-full min-w-0 items-center gap-2">
          <UserCell user={u} />
          {u.id === me?.id && <Badge variant="outline">You</Badge>}
        </span>
      ),
    },
    {
      key: 'email',
      header: 'Email',
      wide: true,
      cell: (u) => <span className="break-all whitespace-normal">{u.email}</span>,
    },
    {
      key: 'role',
      header: 'Role',
      cell: (u) => {
        const shownRole =
          pendingId === u.id && update.variables?.body.role ? update.variables.body.role : u.role
        if (!canAssignRole || u.id === me?.id) return <RoleBadge role={u.role} />
        return (
          <Select
            value={shownRole}
            onValueChange={(v) => changeRole(u, v as Role)}
            disabled={pendingId === u.id}
          >
            <SelectTrigger size="sm" className="w-32" aria-label={`Role for @${u.username}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLES.map((r) => (
                <SelectItem key={r} value={r}>
                  {ROLE_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )
      },
    },
    {
      key: 'verified',
      header: 'Email verified',
      cell: (u) =>
        u.email_verified ? (
          <span className="inline-flex items-center gap-1 text-[0.8125rem] text-muted-foreground">
            <MailCheck className="size-3.5" aria-hidden /> Verified
          </span>
        ) : (
          <Badge variant="warning">
            <MailWarning aria-hidden /> Unverified
          </Badge>
        ),
    },
    {
      key: 'status',
      header: 'Status',
      mobile: 'aside',
      cell: (u) =>
        u.is_active ? (
          <Badge variant="outline">
            <UserCheck aria-hidden /> Active
          </Badge>
        ) : (
          <Badge variant="danger">
            <UserX aria-hidden /> Suspended
          </Badge>
        ),
    },
    {
      key: 'joined',
      header: 'Joined',
      cell: (u) => <DateCell iso={u.created_at} />,
    },
  ]

  if (canManage) {
    columns.push({
      key: 'actions',
      header: 'Account',
      hideHeader: true,
      className: 'text-right',
      mobile: 'actions',
      cell: (u) =>
        u.id === me?.id ? null : (
          <Button
            variant="outline"
            size="sm"
            disabled={pendingId === u.id}
            aria-label={u.is_active ? `Suspend @${u.username}` : `Reactivate @${u.username}`}
            onClick={() => {
              setStatusTarget(u)
              setStatusOpen(true)
            }}
          >
            {u.is_active ? <UserX aria-hidden /> : <UserCheck aria-hidden />}
            {u.is_active ? 'Suspend' : 'Reactivate'}
          </Button>
        ),
    })
  }

  const filtered = !!q || !!role
  const clearFilters = () => {
    setSearch('')
    setRole(undefined)
  }

  return (
    <div>
      <PageHeader
        title="Users"
        description={canAssignRole || canManage ? undefined : 'Role and account changes need an admin.'}
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Users' }]}
      />

      <PagedResults
        query={query}
        skeleton="admin-users"
        label="Users"
        itemLabel="users"
        errorTitle="Could not load users"
        empty={{ icon: Users, title: 'No users yet' }}
        filtered={filtered}
        onClearFilters={clearFilters}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <>
            <SearchField
              id="admin-users-search"
              label="Search users"
              placeholder="Name, username or email"
              value={search}
              onChange={setSearch}
            />
            <FilterSelect
              id="admin-users-role"
              label="Filter by role"
              value={role}
              onChange={setRole}
              options={ROLES}
              labels={ROLE_LABELS}
              allLabel="All roles"
            />
          </>
        }
      >
        {(items) => (
          <AdminTable rows={items} columns={columns} getKey={(u) => u.id} caption="Registered users" />
        )}
      </PagedResults>

      <ConfirmDialog
        open={statusOpen}
        onOpenChange={setStatusOpen}
        title={
          statusTarget?.is_active
            ? `Suspend @${statusTarget.username}?`
            : `Reactivate @${statusTarget?.username ?? ''}?`
        }
        description={
          statusTarget?.is_active
            ? 'They are signed out of every session and can’t sign in until reactivated. This is recorded in the audit log.'
            : 'They can sign in and use BountyFlow again. This is recorded in the audit log.'
        }
        confirmLabel={statusTarget?.is_active ? 'Suspend account' : 'Reactivate account'}
        destructive={!!statusTarget?.is_active}
        pending={update.isPending && update.variables?.body.is_active !== undefined}
        onConfirm={confirmStatus}
      />
    </div>
  )
}
