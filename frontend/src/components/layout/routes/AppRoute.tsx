import { AppLayout } from '../AppLayout'
import { RequireAuth } from '../guards'

/** Lazy route module: authenticated workspace shell. */
export default function AppRoute() {
  return (
    <RequireAuth>
      <AppLayout />
    </RequireAuth>
  )
}
