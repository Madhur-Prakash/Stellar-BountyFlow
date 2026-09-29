import { RotateCcw, X } from 'lucide-react'
import { useRef, useState } from 'react'

import { ReasonDialog } from '@/components/common/ReasonDialog'
import { Button } from '@/components/ui/button'
import { chainApi } from '@/lib/api/endpoints'
import type { Submission } from '@/lib/api/types'

import { useChainFlow } from './ChainFlow'

/**
 * Request changes or reject a submission whose review clock runs on-chain. The feedback is collected first;
 * the requester then signs `request_changes` / `reject_submission`, which stops the clock. BountyFlow applies
 * the same review once the transaction is confirmed.
 */
export function OnchainAnswerButtons({ submission }: { submission: Submission }) {
  const [dialog, setDialog] = useState<'revise' | 'reject' | null>(null)
  const [kind, setKind] = useState<'REQUEST_CHANGES' | 'REJECT_SUBMISSION'>('REQUEST_CHANGES')
  const feedback = useRef('')
  const action = useRef<'REQUEST_CHANGES' | 'REJECT_SUBMISSION'>('REQUEST_CHANGES')
  const flow = useChainFlow({
    title: 'Answer on-chain',
    prepare: (wallet_address) =>
      chainApi.prepare(submission.bounty_id, {
        action: action.current,
        wallet_address,
        submission_id: submission.id,
        feedback: feedback.current,
      }),
  })
  const start = (next: 'REQUEST_CHANGES' | 'REJECT_SUBMISSION', text: string) => {
    action.current = next
    feedback.current = text
    setKind(next)
    setDialog(null)
    flow.run()
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setDialog('revise')}>
        <RotateCcw /> Request revision
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="text-destructive hover:text-destructive sm:ml-auto"
        onClick={() => setDialog('reject')}
      >
        <X /> Reject
      </Button>
      <ReasonDialog
        open={dialog === 'revise'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Request a revision"
        description="This work is recorded on-chain, so you sign the request with your wallet. It stops the review clock."
        label="What needs to change?"
        minLength={10}
        confirmLabel="Continue to sign"
        onConfirm={(text) => start('REQUEST_CHANGES', text)}
      />
      <ReasonDialog
        open={dialog === 'reject'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Reject this submission?"
        description="You sign the rejection with your wallet. The contributor stays assigned and can raise a dispute."
        label="Reason"
        minLength={10}
        confirmLabel="Continue to sign"
        destructive
        onConfirm={(text) => start('REJECT_SUBMISSION', text)}
      />
      {flow.dialog({
        description:
          kind === 'REQUEST_CHANGES'
            ? 'Ask for changes on-chain. The contributor’s next submission starts a full review window.'
            : 'Reject the work on-chain. It can then only move on through a dispute.',
      })}
    </>
  )
}
