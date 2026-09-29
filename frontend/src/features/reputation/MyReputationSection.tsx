import { Download, LoaderCircle, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { PaginationBar } from '@/components/layout/PaginationBar'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { CardQuery } from '@/features/app/workspace-ui'
import { errorMessage } from '@/lib/api/client'
import {
  saveCredentialFile,
  useCredentialIssuer,
  useIssueCredential,
  useMyAttestations,
  useReputationSummary,
} from '@/lib/api/queries/reputation'
import type { Attestation, IssuedCredential } from '@/lib/api/types'

import { AttestationRows } from './AttestationRows'

function fileName(credential: IssuedCredential) {
  const kind = credential.kind === 'SUMMARY' ? 'summary' : 'completion'
  return `bountyflow-${kind}-credential-${credential.id.slice(0, 8)}.json`
}

/** The workspace profile's "Completed on-chain" section, with credential downloads for the owner. */
export function MyReputationSection({ username }: { username: string }) {
  const [page, setPage] = useState(1)
  const query = useMyAttestations({ page, page_size: 10 })
  const summary = useReputationSummary(username)
  const issuer = useCredentialIssuer()
  const issue = useIssueCredential()
  const [busy, setBusy] = useState<string | null>(null)

  const credentialsOn = issuer.data?.enabled === true
  const attested = summary.data?.attested_completions ?? 0

  const download = (target: { attestationId: string } | 'summary') => {
    const key = target === 'summary' ? 'summary' : target.attestationId
    setBusy(key)
    issue.mutate(target, {
      onSuccess: (credential) => {
        saveCredentialFile(credential.document, fileName(credential))
        toast.success('Credential downloaded')
      },
      onError: (e) => toast.error(errorMessage(e)),
      onSettled: () => setBusy(null),
    })
  }

  const rowAction = (a: Attestation) =>
    credentialsOn && a.status === 'CONFIRMED' ? (
      <Button
        variant="outline"
        size="sm"
        disabled={busy !== null}
        onClick={() => download({ attestationId: a.id })}
        aria-label={`Download credential for ${a.bounty.title}`}
      >
        {busy === a.id ? <LoaderCircle className="animate-spin" /> : <Download />} Download credential
      </Button>
    ) : null

  return (
    <section id="reputation" aria-labelledby="reputation-h">
      <Card className="gap-0">
        <CardHeader className="flex flex-col gap-3 pb-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1.5">
            <CardTitle>
              <h2 id="reputation-h">Completed on-chain</h2>
            </CardTitle>
            <CardDescription>
              Each verified payout is recorded in the attestation registry on Stellar.
            </CardDescription>
          </div>
          {credentialsOn && attested > 0 && (
            <Button variant="outline" disabled={busy !== null} onClick={() => download('summary')}>
              {busy === 'summary' ? <LoaderCircle className="animate-spin" /> : <Download />} Download summary
            </Button>
          )}
        </CardHeader>
        <div className="border-t">
          <CardQuery
            query={query}
            skeleton="app-profile-attestations"
            rows={2}
            isEmpty={(d) => d.items.length === 0}
            empty={{
              icon: ShieldCheck,
              title: 'Nothing recorded on-chain yet',
              description:
                summary.data && !summary.data.enabled
                  ? 'On-chain attestations are not set up on this server.'
                  : 'When a payout to you is verified, it is attested here within a minute.',
            }}
          >
            {(data) => (
              <>
                <AttestationRows items={data.items} label="Your completions" actions={rowAction} />
                {data.pages > 1 && (
                  <div className="border-t px-4 pb-3 sm:px-5">
                    <PaginationBar
                      page={data.page}
                      pages={data.pages}
                      total={data.total}
                      pageSize={data.page_size}
                      onPageChange={setPage}
                      itemLabel="completions"
                    />
                  </div>
                )}
              </>
            )}
          </CardQuery>
        </div>
        <CardFooter className="flex flex-wrap justify-between gap-2 border-t px-5 py-3 text-[0.8125rem] text-muted-foreground">
          <span>
            {issuer.data && !credentialsOn
              ? 'Credential downloads are not set up on this server.'
              : 'Credentials are W3C Verifiable Credentials signed by this site.'}
          </span>
          <Link to="/credentials/verify" className="font-medium text-primary-emphasis hover:underline">
            Verify a credential
          </Link>
        </CardFooter>
      </Card>
    </section>
  )
}
