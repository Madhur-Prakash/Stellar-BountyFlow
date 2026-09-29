import { useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { ChainActionDialog } from '@/components/chain/ChainActionDialog'
import type { BlockchainTransaction, PreparedTransaction } from '@/lib/api/types'
import { useChainAction } from '@/lib/stellar/useChainAction'

/**
 * A chain action started from code (after another dialog collected its input), shown in the shared
 * ChainActionDialog. `run` opens the dialog and prepares the transaction.
 */
export function useChainFlow({
  title,
  prepare,
  onConfirmed,
}: {
  title: string
  prepare: (walletAddress: string) => Promise<PreparedTransaction>
  onConfirmed?: (tx: BlockchainTransaction) => void
}) {
  const [open, setOpenState] = useState(false)
  const openRef = useRef(false)
  const controller = useChainAction({
    prepare,
    holdInvalidation: () => openRef.current,
    onConfirmed: (tx) => {
      toast.success(`${title}: confirmed on Stellar`)
      onConfirmed?.(tx)
    },
  })
  const setOpen = (next: boolean) => {
    openRef.current = next
    setOpenState(next)
    if (!next) controller.flush()
  }
  const run = () => {
    setOpen(true)
    void controller.start()
  }
  const dialog = (props: { description?: string; children?: ReactNode }) => (
    <ChainActionDialog
      controller={controller}
      open={open}
      onOpenChange={setOpen}
      title={title}
      description={props.description}
    >
      {props.children}
    </ChainActionDialog>
  )
  return { run, dialog, controller }
}
