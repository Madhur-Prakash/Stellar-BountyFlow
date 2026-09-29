import { Coins, LoaderCircle, Plus, RefreshCw, Rocket } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { MonoValue } from '@/components/common/MonoValue'
import { Bones } from '@/components/layout/Bones'
import { ErrorState } from '@/components/layout/ErrorState'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { AssetOperationButton } from '@/features/app/assets/AssetOperationDialog'
import { errorMessage } from '@/lib/api/client'
import { adminAssetsApi } from '@/lib/api/endpoints'
import { useAdminAssets, useCreateAsset, useUpdateAsset, useVerifyAsset } from '@/lib/api/queries/assets'
import { usePublicConfig } from '@/lib/api/queries/config'
import type { AdminRewardAsset } from '@/lib/api/types'
import { formatNumber, formatRelative } from '@/lib/format'
import { accountExplorerUrl, contractExplorerUrl } from '@/lib/stellar/explorer'
import { useWalletStore } from '@/stores/wallet'

import { AdminTable, type AdminColumn } from './admin-shared'

/** Issuer flags worth surfacing: they change what the issuer can do to holders. */
const FLAG_LABELS: Record<string, string> = {
  auth_required: 'Authorization required',
  auth_revocable: 'Revocable',
  auth_clawback_enabled: 'Clawback enabled',
  auth_immutable: 'Immutable',
}

function AddAssetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const create = useCreateAsset()
  const [code, setCode] = useState('')
  const [issuer, setIssuer] = useState('')
  const [name, setName] = useState('')
  const [contractId, setContractId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const byContract = contractId.trim().length > 0
  const ready = byContract || (code.trim().length > 0 && issuer.trim().length > 0)

  const submit = () => {
    setError(null)
    create.mutate(
      byContract
        ? { contract_id: contractId.trim(), name: name.trim() || undefined }
        : { code: code.trim(), issuer: issuer.trim(), name: name.trim() || undefined },
      {
        onSuccess: (asset) => {
          toast.success(
            asset.contract_status === 'DEPLOYED'
              ? `${asset.asset.code} added`
              : `${asset.asset.code} added. Deploy its asset contract before enabling it.`,
          )
          onOpenChange(false)
          setCode('')
          setIssuer('')
          setName('')
          setContractId('')
        },
        onError: (e) => setError(errorMessage(e)),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add a reward asset</DialogTitle>
          <DialogDescription>
            A classic Stellar asset by code and issuer, or the id of its Stellar Asset Contract. BountyFlow
            derives the contract address, reads its decimals and symbol, and checks the issuer on the network.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-[8rem_minmax(0,1fr)]">
            <div className="space-y-1.5">
              <Label htmlFor="asset-code">Code</Label>
              <Input
                id="asset-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                disabled={byContract}
                placeholder="USDC"
                maxLength={12}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="asset-issuer">Issuer</Label>
              <Input
                id="asset-issuer"
                value={issuer}
                onChange={(e) => setIssuer(e.target.value)}
                disabled={byContract}
                placeholder="G…"
                className="font-mono text-[0.8125rem]"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="asset-contract">Stellar Asset Contract id</Label>
            <Input
              id="asset-contract"
              value={contractId}
              onChange={(e) => setContractId(e.target.value)}
              placeholder="C…"
              className="font-mono text-[0.8125rem]"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="asset-name">Name</Label>
            <Input
              id="asset-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="USD Coin"
              maxLength={80}
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!ready || create.isPending} onClick={submit}>
            {create.isPending && <LoaderCircle className="animate-spin" />} Add asset
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeployButton({ asset }: { asset: AdminRewardAsset }) {
  const address = useWalletStore((s) => s.address)
  const connect = useWalletStore((s) => s.connect)
  if (!address) {
    return (
      <Button size="sm" variant="outline" onClick={() => void connect()}>
        <Rocket /> Connect wallet to deploy
      </Button>
    )
  }
  return (
    <AssetOperationButton
      size="sm"
      variant="outline"
      label="Deploy contract"
      title={`Deploy the ${asset.asset.code} asset contract`}
      description="Anyone may deploy an asset's Stellar Asset Contract; it is derived from the asset itself, so the result is the same address for everyone."
      confirmedToast={`${asset.asset.code} asset contract deployed`}
      prepare={() => adminAssetsApi.prepareDeploy(asset.id, address)}
    />
  )
}

export default function AdminAssetsPage() {
  const query = useAdminAssets()
  const update = useUpdateAsset()
  const verify = useVerifyAsset()
  const { data: config } = usePublicConfig()
  const [adding, setAdding] = useState(false)

  const columns: AdminColumn<AdminRewardAsset>[] = [
    {
      key: 'asset',
      header: 'Asset',
      mobile: 'title',
      cell: (a) => (
        <div>
          <div className="leading-5 font-medium">
            {a.asset.code}
            {a.is_default && <span className="ml-2 text-xs text-muted-foreground">Default</span>}
          </div>
          <div className="text-xs leading-4 text-muted-foreground">{a.name}</div>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      mobile: 'aside',
      cell: (a) =>
        a.contract_status === 'DEPLOYED' ? (
          a.is_enabled ? (
            <Badge variant="info">Enabled</Badge>
          ) : (
            <Badge variant="muted">Disabled</Badge>
          )
        ) : (
          <Badge variant="warning">Contract not deployed</Badge>
        ),
    },
    {
      key: 'contract',
      header: 'Asset contract',
      cell: (a) => (
        <MonoValue
          value={a.asset.contract_id}
          label={`${a.asset.code} asset contract id`}
          href={contractExplorerUrl(config, a.asset.contract_id)}
          lead={4}
          tail={4}
        />
      ),
    },
    {
      key: 'issuer',
      header: 'Issuer',
      cell: (a) =>
        a.asset.issuer ? (
          <MonoValue
            value={a.asset.issuer}
            label={`${a.asset.code} issuer`}
            href={accountExplorerUrl(config, a.asset.issuer)}
            lead={4}
            tail={4}
          />
        ) : (
          <span className="text-muted-foreground">Native asset</span>
        ),
    },
    {
      key: 'bounties',
      header: 'Bounties',
      className: 'text-right',
      cell: (a) => <span className="tabular-nums">{formatNumber(a.bounty_count)}</span>,
    },
    {
      key: 'enabled',
      header: 'Enabled',
      mobile: 'actions',
      className: 'text-right',
      cell: (a) => (
        <div className="flex items-center justify-end gap-2">
          <Label htmlFor={`enabled-${a.id}`} className="sr-only">
            {a.is_enabled ? `Disable ${a.asset.code}` : `Enable ${a.asset.code}`}
          </Label>
          <Switch
            id={`enabled-${a.id}`}
            checked={a.is_enabled}
            disabled={update.isPending || a.contract_status !== 'DEPLOYED'}
            onCheckedChange={(value) =>
              update.mutate(
                { id: a.id, body: { is_enabled: value } },
                {
                  onSuccess: () =>
                    toast.success(value ? `${a.asset.code} enabled` : `${a.asset.code} disabled`),
                  onError: (e) => toast.error(errorMessage(e)),
                },
              )
            }
          />
        </div>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Reward assets' }]}
        title="Reward assets"
        description="Which assets bounties can pay in on this network. Amounts are always recorded per asset."
        actions={
          <Button onClick={() => setAdding(true)}>
            <Plus /> Add asset
          </Button>
        }
      />
      {query.isError ? (
        <ErrorState error={query.error} title="Could not load assets" onRetry={() => void query.refetch()} />
      ) : (
        <Bones
          name="admin-assets"
          loading={query.isPending}
          fallback={<Skeleton className="h-72 rounded-xl" />}
        >
          {query.isPending ? null : (
            <div className="overflow-hidden rounded-xl border bg-card shadow-soft">
              <AdminTable
                rows={query.data}
                columns={columns}
                getKey={(a) => a.id}
                caption="Reward assets"
                detailLabel={(a) => `Show details for ${a.asset.code}`}
                detail={(a) => (
                  <div className="space-y-3 text-sm">
                    <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
                      <div className="flex justify-between gap-3">
                        <dt className="text-muted-foreground">Identifier</dt>
                        <dd className="font-mono text-[0.8125rem]">{a.asset.identifier}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-muted-foreground">Symbol on contract</dt>
                        <dd>{a.symbol ?? '—'}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-muted-foreground">Decimals</dt>
                        <dd className="tabular-nums">{a.decimals}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-muted-foreground">Last checked on-chain</dt>
                        <dd>{a.verified_at ? formatRelative(a.verified_at) : 'Never'}</dd>
                      </div>
                    </dl>
                    {Object.entries(a.issuer_flags).some(([, on]) => on) && (
                      <ul className="flex flex-wrap gap-1.5" aria-label="Issuer flags">
                        {Object.entries(a.issuer_flags)
                          .filter(([, on]) => on)
                          .map(([flag]) => (
                            <li key={flag}>
                              <Badge variant="outline">{FLAG_LABELS[flag] ?? flag}</Badge>
                            </li>
                          ))}
                      </ul>
                    )}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={verify.isPending}
                        onClick={() =>
                          verify.mutate(a.id, {
                            onSuccess: (fresh) =>
                              toast.success(
                                fresh.contract_status === 'DEPLOYED'
                                  ? `${fresh.asset.code} verified on-chain`
                                  : `${fresh.asset.code}: no asset contract on this network yet`,
                              ),
                            onError: (e) => toast.error(errorMessage(e)),
                          })
                        }
                      >
                        <RefreshCw /> Check on-chain
                      </Button>
                      {a.contract_status !== 'DEPLOYED' && <DeployButton asset={a} />}
                    </div>
                  </div>
                )}
              />
              {query.data.length === 0 && (
                <p className="flex items-center gap-2 px-4 py-10 text-sm text-muted-foreground">
                  <Coins className="size-4" aria-hidden /> No reward assets on this network.
                </p>
              )}
            </div>
          )}
        </Bones>
      )}
      <AddAssetDialog open={adding} onOpenChange={setAdding} />
    </div>
  )
}
