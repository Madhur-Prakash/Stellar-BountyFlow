import { STAFF_PERMISSION } from '@/lib/permissions'

import { AdminLayout } from '../AdminLayout'
import { RequireAuth, RequirePermission } from '../guards'

/** Lazy route module: staff console, gated by the "bounty:moderate" permission. */
export default function AdminRoute() {
  return (
    <RequireAuth>
      <RequirePermission permission={STAFF_PERMISSION}>
        <AdminLayout />
      </RequirePermission>
    </RequireAuth>
  )
}
