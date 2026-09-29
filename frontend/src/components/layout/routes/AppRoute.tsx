import { LegalGate } from '@/features/app/privacy/LegalGate'

import { AppLayout } from '../AppLayout'
import { RequireAuth } from '../guards'

/** Lazy route module: authenticated workspace shell, held back until the current terms are accepted. */
export default function AppRoute() {
  return (
    <RequireAuth>
      <LegalGate>
        <AppLayout />
      </LegalGate>
    </RequireAuth>
  )
}
