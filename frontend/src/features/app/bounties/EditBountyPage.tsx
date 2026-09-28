import { Lock } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { EmptyState } from '@/components/layout/EmptyState'
import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { useBounty, useUpdateBounty } from '@/lib/api/queries/bounties'

import { fromBounty } from './bounty-form-schema'
import { BountyForm } from './BountyForm'

export default function EditBountyPage() {
  const { bountyId = '' } = useParams()
  const query = useBounty(bountyId)
  const update = useUpdateBounty(bountyId)
  const navigate = useNavigate()

  return (
    <div className="mx-auto max-w-6xl">
      <QueryView query={query} errorTitle="Could not load this bounty">
        {(bounty) => {
          const editable =
            bounty.status === 'DRAFT' || (bounty.status === 'OPEN' && bounty.funding_status === 'UNFUNDED')
          return (
            <>
              <PageHeader
                breadcrumbs={[
                  { label: 'My bounties', to: '/app/bounties' },
                  { label: bounty.title, to: `/app/bounties/${bounty.id}` },
                  { label: 'Edit' },
                ]}
                title="Edit bounty"
              />
              {!bounty.viewer?.is_owner ? (
                <EmptyState icon={Lock} title="Only the requester can edit this bounty" />
              ) : !editable ? (
                <EmptyState
                  icon={Lock}
                  title="This bounty can no longer be edited"
                  description="Content is locked once a bounty is funded."
                  action={
                    <Button asChild variant="outline">
                      <Link to={`/app/bounties/${bounty.id}`}>Back to bounty</Link>
                    </Button>
                  }
                />
              ) : (
                <BountyForm
                  defaultValues={fromBounty(bounty)}
                  submitLabel="Save changes"
                  lockEconomics={bounty.status !== 'DRAFT'}
                  status={bounty.status}
                  pending={update.isPending}
                  cancelTo={`/app/bounties/${bounty.id}`}
                  footerNote={
                    bounty.status === 'DRAFT' ? undefined : 'Content can change until the bounty is funded.'
                  }
                  onSubmit={async (body) => {
                    await update.mutateAsync(body)
                    toast.success('Bounty updated')
                    navigate(`/app/bounties/${bounty.id}`)
                  }}
                />
              )}
            </>
          )
        }}
      </QueryView>
    </div>
  )
}
