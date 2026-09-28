import type { LucideIcon } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import type { BlockchainTransaction, PreparedTransaction } from '@/lib/api/types'
import { useChainAction } from '@/lib/stellar/useChainAction'

import { ChainActionDialog } from './ChainActionDialog'

/**
 * Button that runs one on-chain action end to end (prepare → review → sign →
 * submit → confirm) inside the shared ChainActionDialog.
 */
export function ChainActionButton({
  label,
  title,
  description,
  prepare,
  icon: Icon,
  variant = 'default',
  size = 'default',
  disabled,
  onConfirmed,
  className,
  children,
}: {
  label: string
  title: string
  description?: string
  prepare: (walletAddress: string) => Promise<PreparedTransaction>
  icon?: LucideIcon
  variant?: 'default' | 'outline' | 'secondary' | 'ghost' | 'destructive'
  size?: 'default' | 'sm' | 'lg'
  disabled?: boolean
  onConfirmed?: (tx: BlockchainTransaction) => void
  className?: string
  /** Extra context rendered in the dialog above the transaction summary. */
  children?: ReactNode
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
    // Refresh the page's data once the user has seen the outcome.
    if (!next) controller.flush()
  }

  return (
    <>
      <Button
        variant={variant}
        size={size}
        className={className}
        disabled={disabled || controller.isBusy}
        onClick={() => {
          setOpen(true)
          if (controller.step === 'idle' || controller.step === 'failed' || controller.step === 'confirmed') {
            void controller.start()
          }
        }}
      >
        {Icon && <Icon />}
        {controller.step === 'confirming' ? 'Confirming…' : label}
      </Button>
      <ChainActionDialog
        controller={controller}
        open={open}
        onOpenChange={setOpen}
        title={title}
        description={description}
      >
        {children}
      </ChainActionDialog>
    </>
  )
}
