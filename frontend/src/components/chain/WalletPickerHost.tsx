import { lazy, Suspense, useEffect } from 'react'

import { useWalletStore } from '@/stores/wallet'

const WalletPickerDialog = lazy(() => import('./WalletPickerDialog'))

/**
 * Mounts the wallet picker once for the workspace and restores the remembered wallet silently. The dialog (and
 * the wallet SDKs it lists) load only when it is first opened.
 */
export function WalletPickerHost() {
  const pickerOpen = useWalletStore((s) => s.pickerOpen)
  const status = useWalletStore((s) => s.status)
  const detect = useWalletStore((s) => s.detect)

  useEffect(() => {
    if (status === 'unknown') void detect()
  }, [status, detect])

  if (!pickerOpen) return null
  return (
    <Suspense fallback={null}>
      <WalletPickerDialog />
    </Suspense>
  )
}
