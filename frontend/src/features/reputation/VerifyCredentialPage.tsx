import { CircleCheck, CircleMinus, CircleX, FileJson, LoaderCircle, Upload } from 'lucide-react'
import { useCallback, useId, useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router'

import { MonoValue } from '@/components/common/MonoValue'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { useCredentialIssuer, useVerifyCredential } from '@/lib/api/queries/reputation'
import type { VerificationCheck, VerificationReport } from '@/lib/api/types'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const MAX_BYTES = 256 * 1024

const CHECK_ICON = {
  pass: CircleCheck,
  fail: CircleX,
  skip: CircleMinus,
} as const

const CHECK_TONE = {
  pass: 'text-success',
  fail: 'text-destructive',
  skip: 'text-muted-foreground',
} as const

function CheckRow({ check }: { check: VerificationCheck }) {
  const Icon = CHECK_ICON[check.status]
  return (
    <li className="flex items-start gap-3 px-4 py-3 sm:px-5">
      <Icon className={cn('mt-0.5 size-4 shrink-0', CHECK_TONE[check.status])} aria-hidden />
      <div className="min-w-0">
        <p className="text-sm font-medium">
          {check.label}
          <span className="sr-only">: {check.status === 'pass' ? 'passed' : check.status}</span>
        </p>
        <p className="mt-0.5 text-[0.8125rem] leading-relaxed text-muted-foreground">{check.detail}</p>
      </div>
    </li>
  )
}

function Report({ report }: { report: VerificationReport }) {
  const kind = report.kind === 'summary' ? 'Summary of attested completions' : 'Bounty completion'
  return (
    <Card className="gap-0" aria-live="polite">
      <CardHeader className="pb-5">
        <CardTitle>
          <h2 className="flex flex-wrap items-center gap-2.5">
            {report.verified ? 'Credential verified' : 'Credential not verified'}
            <Badge variant={report.verified ? 'success' : 'danger'}>
              {report.verified ? 'Valid' : 'Invalid'}
            </Badge>
          </h2>
        </CardTitle>
        <CardDescription>
          {report.credential_id
            ? `${kind} · checked ${formatDateTime(report.checked_at)}`
            : 'Checked just now'}
        </CardDescription>
      </CardHeader>
      <ul aria-label="Verification checks" className="divide-y border-t">
        {report.checks.map((c) => (
          <CheckRow key={c.id} check={c} />
        ))}
      </ul>
      {(report.subject || report.credential_id) && (
        <div className="space-y-3 border-t px-4 py-4 sm:px-5">
          {report.subject && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Subject</p>
              <MonoValue value={report.subject} label="credential subject" className="-my-1" />
            </div>
          )}
          {report.credential_id && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Credential id</p>
              <MonoValue value={report.credential_id} label="credential id" className="-my-1" lead={12} />
            </div>
          )}
        </div>
      )}
      {report.attestations.length > 0 && (
        <div className="border-t px-4 py-4 sm:px-5">
          <p className="text-xs text-muted-foreground">On-chain attestations</p>
          <ul className="mt-2 space-y-2">
            {report.attestations.map((a) => (
              <li key={a.onchain_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                {a.attestation_path ? (
                  <Link to={a.attestation_path} className="font-medium hover:underline">
                    Attestation #{a.onchain_id}
                  </Link>
                ) : (
                  <span className="font-medium">Attestation #{a.onchain_id}</span>
                )}
                <span className="text-[0.8125rem] text-muted-foreground">{a.detail}</span>
                {a.explorer_url && (
                  <a
                    href={a.explorer_url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="text-[0.8125rem] font-medium text-primary-emphasis hover:underline"
                  >
                    Transaction
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

export default function VerifyCredentialPage() {
  const inputId = useId()
  const fileRef = useRef<HTMLInputElement>(null)
  const [text, setText] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const verify = useVerifyCredential()
  const issuer = useCredentialIssuer()

  const readFile = useCallback(async (file: File) => {
    if (file.size > MAX_BYTES) {
      setParseError('That file is too large to be a credential.')
      return
    }
    setParseError(null)
    setText(await file.text())
  }, [])

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) void readFile(file)
  }

  const onVerify = () => {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(text) as Record<string, unknown>
    } catch {
      setParseError('That is not valid JSON. Paste the credential exactly as it was downloaded.')
      return
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setParseError('A credential is a JSON object.')
      return
    }
    setParseError(null)
    verify.mutate(parsed)
  }

  return (
    <PageContainer className="pt-10 pb-16 sm:pt-14 sm:pb-20">
      <PageHeader
        size="display"
        eyebrow={<span className="label-mono">Credentials</span>}
        title={<span className="font-display font-bold">Verify a credential</span>}
        description="Paste or drop a BountyFlow credential. Its signature, status and on-chain attestation are checked here."
      />
      <div className="grid gap-6 lg:grid-cols-2 lg:gap-8">
        <Card className="gap-0">
          <CardHeader className="pb-5">
            <CardTitle>
              <h2>Credential</h2>
            </CardTitle>
            <CardDescription>The JSON file a contributor downloaded from their profile.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 border-t pt-5">
            <div
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                'rounded-xl border border-dashed p-4 transition-colors',
                dragging ? 'border-primary bg-primary/5' : 'border-border',
              )}
            >
              <Label htmlFor={inputId}>Credential JSON</Label>
              <Textarea
                id={inputId}
                rows={12}
                spellCheck={false}
                value={text}
                onChange={(e) => {
                  setText(e.target.value)
                  setParseError(null)
                }}
                placeholder='{"@context": ["https://www.w3.org/ns/credentials/v2"], …}'
                className="mt-2 font-mono text-[0.8125rem]"
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                  <Upload /> Choose a file
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="application/json,.json,.jsonld"
                  className="sr-only"
                  aria-label="Credential file"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) void readFile(file)
                  }}
                />
                <span className="text-xs text-muted-foreground">or drop it here</span>
              </div>
            </div>
            {parseError && <p className="text-sm text-destructive">{parseError}</p>}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={onVerify} disabled={!text.trim() || verify.isPending}>
                {verify.isPending ? <LoaderCircle className="animate-spin" /> : <FileJson />} Verify
              </Button>
              {text && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setText('')
                    setParseError(null)
                    verify.reset()
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
            {issuer.data?.did && (
              <p className="text-[0.8125rem] text-muted-foreground">
                This site issues credentials as{' '}
                <a
                  href={issuer.data.did_document_url ?? '#'}
                  className="font-medium text-primary-emphasis hover:underline"
                >
                  {issuer.data.did}
                </a>{' '}
                with the {issuer.data.cryptosuite} cryptosuite.
              </p>
            )}
            {issuer.data && !issuer.data.enabled && (
              <p className="text-[0.8125rem] text-muted-foreground">
                Credentials are not set up on this server, so nothing can be verified here.
              </p>
            )}
          </CardContent>
        </Card>

        <div className="min-w-0">
          {verify.isError && <ErrorState error={verify.error} title={errorMessage(verify.error)} />}
          {verify.data && <Report report={verify.data} />}
          {!verify.data && !verify.isError && (
            <Card className="gap-0">
              <CardHeader className="pb-5">
                <CardTitle>
                  <h2>What is checked</h2>
                </CardTitle>
              </CardHeader>
              <ul className="divide-y border-t text-sm">
                {[
                  ['Credential format', 'A W3C Verifiable Credential 2.0 with a proof.'],
                  ['Issuer', 'The credential was issued by this site.'],
                  ['Signature', 'The eddsa-jcs-2022 proof verifies with the issuer’s published key.'],
                  ['Validity period', 'The credential is in date.'],
                  ['Revocation status', 'Its entry in the public status list is not set.'],
                  [
                    'On-chain attestation',
                    'The registry’s record matches the payment the credential states.',
                  ],
                ].map(([label, detail]) => (
                  <li key={label} className="px-4 py-3 sm:px-5">
                    <p className="font-medium">{label}</p>
                    <p className="mt-0.5 text-[0.8125rem] text-muted-foreground">{detail}</p>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </PageContainer>
  )
}
