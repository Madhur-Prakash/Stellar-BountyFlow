import type { Me, Permission } from '@/lib/api/types'

/** UI gating is by permission (from `Me.permissions`), never by role name. */
export function hasPermission(
  me: Pick<Me, 'permissions'> | null | undefined,
  permission: Permission,
): boolean {
  return !!me && Array.isArray(me.permissions) && me.permissions.includes(permission)
}

export function hasAnyPermission(
  me: Pick<Me, 'permissions'> | null | undefined,
  permissions: Permission[],
): boolean {
  return permissions.some((p) => hasPermission(me, p))
}

/** Any staff member (moderator or admin) holds this; it unlocks the /admin area. */
export const STAFF_PERMISSION: Permission = 'bounty:moderate'
