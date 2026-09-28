import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { useCreateBounty } from '@/lib/api/queries/bounties'

import { EMPTY_BOUNTY_FORM } from './bounty-form-schema'
import { BountyForm } from './BountyForm'

export default function CreateBountyPage() {
  const create = useCreateBounty()
  const navigate = useNavigate()
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        breadcrumbs={[{ label: 'My bounties', to: '/app/bounties' }, { label: 'New bounty' }]}
        title="Post a bounty"
        description="Saved as a private draft. You’ll review it, publish it, and then fund the escrow."
      />
      <BountyForm
        defaultValues={EMPTY_BOUNTY_FORM}
        submitLabel="Save draft"
        pending={create.isPending}
        onSubmit={async (body) => {
          const bounty = await create.mutateAsync(body)
          toast.success('Draft saved')
          navigate(`/app/bounties/${bounty.id}`, { replace: true })
        }}
      />
    </div>
  )
}
