import { LoaderCircle, Plus, ShieldBan, ShieldCheck, X } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { MonoValue } from '@/components/common/MonoValue'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { StatGrid, StatTile } from '@/components/common/StatTile'
import { Bones } from '@/components/layout/Bones'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage, isApiError } from '@/lib/api/client'
import {
  useAddScreeningEntry,
  useMe,
  useRemoveScreeningEntry,
  useScreeningDecisions,
  useScreeningEntries,
  useScreeningStatus,
} from '@/lib/api/queries'
import type { ScreeningDecision, ScreeningEntry, ScreeningSource } from '@/lib/api/types'
import { formatDateTime, formatNumber, formatRelative, humanize } from '@/lib/format'
import { hasPermission } from '@/lib/permissions'
import { useDebounce } from '@/hooks/useDebounce'

import {
  AdminTable,
  ClampedText,
  DateCell,
  FilterSelect,
  PagedResults,
  SearchField,
  UserCell,
  type AdminColumn,
} from './admin-shared'
import { ADMIN_PAGE_SIZE, scrollToTop, useFilteredPage } from './admin-utils'

const SOURCES: readonly ScreeningSource[] = ['MANUAL', 'LIST']
const SOURCE_LABELS: Record<ScreeningSource, string> = { MANUAL: 'Manual', LIST: 'Sanctions list' }

/** "chain:PAYOUT" → "Payout"; "wallet_verification" → "Wallet verification". */
function contextLabel(context: string): string {
  const [kind, action] = context.split(':')
  if (kind === 'chain' && action) return humanize(action)
  return humanize(context)
}

function StatusStrip() {
  const query = useScreeningStatus()
  const s = query.data
  const list = s?.list
  const listHint = !list
    ? undefined
    : !list.configured
      ? 'No list configured'
      : list.error
        ? `Last sync failed: ${list.error}`
        : list.loaded_at
          ? `Synced ${formatRelative(list.loaded_at)}`
          : 'Not synced yet'
  return (
    <Bones name="admin-screening-status" loading={query.isPending}>
      <StatGrid className="grid-cols-1 sm:grid-cols-3">
        <StatTile
          label="Screening"
          value={s ? (s.enabled ? 'On' : 'Off') : '—'}
          hint={s ? `Provider: ${s.provider}` : undefined}
        />
        <StatTile
          label="Manual entries"
          value={s ? formatNumber(s.manual_entries) : '—'}
          hint="Added by admins"
        />
        <StatTile
          label={list?.name ?? 'Sanctions list'}
          value={s ? formatNumber(s.list_entries) : '—'}
          hint={listHint}
        />
      </StatGrid>
    </Bones>
  )
}

function DecisionsList() {
  const [search, setSearch] = useState('')
  const q = useDebounce(search.trim(), 300)
  const [page, setPage] = useFilteredPage(q)
  const query = useScreeningDecisions({
    result: 'blocked',
    q: q || undefined,
    page,
    page_size: ADMIN_PAGE_SIZE,
  })
  const columns: AdminColumn<ScreeningDecision>[] = [
    {
      key: 'user',
      header: 'Account',
      mobile: 'title',
      cell: (d) =>
        d.user ? <UserCell user={d.user} avatar={false} /> : <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'address',
      header: 'Address',
      cell: (d) => <MonoValue value={d.address} label="address" lead={5} tail={5} />,
    },
    {
      key: 'context',
      header: 'Blocked at',
      cell: (d) => (
        <span className="whitespace-nowrap">
          {contextLabel(d.context)}
          {d.bounty_id && (
            <>
              {' '}
              <Link to={`/bounties/${d.bounty_id}`} className="text-primary-emphasis hover:underline">
                bounty
              </Link>
            </>
          )}
        </span>
      ),
    },
    {
      key: 'reason',
      header: 'Match',
      wide: true,
      cell: (d) => (
        <ClampedText
          text={d.matches.map((m) => `${m.list_name}${m.reason ? `: ${m.reason}` : ''}`).join('; ')}
          className="lg:min-w-48"
        />
      ),
    },
    {
      key: 'when',
      header: 'When',
      mobile: 'aside',
      cell: (d) => (
        <time
          dateTime={d.created_at}
          title={formatDateTime(d.created_at)}
          className="whitespace-nowrap text-muted-foreground"
        >
          {formatRelative(d.created_at)}
        </time>
      ),
    },
  ]
  return (
    <PagedResults
      query={query}
      skeleton="admin-screening-decisions"
      label="Blocked screening decisions"
      itemLabel="blocked attempts"
      errorTitle="Could not load screening decisions"
      empty={{ icon: ShieldCheck, title: 'Nothing blocked yet' }}
      filtered={!!q}
      onClearFilters={() => setSearch('')}
      onPageChange={(p) => {
        setPage(p)
        scrollToTop()
      }}
      toolbar={
        <SearchField
          id="screening-decisions-search"
          label="Search by address"
          value={search}
          onChange={setSearch}
          placeholder="Address"
          maxLength={56}
        />
      }
    >
      {(items) => (
        <AdminTable
          rows={items}
          columns={columns}
          getKey={(d) => d.id}
          caption="Blocked screening decisions"
        />
      )}
    </PagedResults>
  )
}

function EntriesList({ canManage }: { canManage: boolean }) {
  const [search, setSearch] = useState('')
  const [source, setSource] = useState<ScreeningSource | undefined>(undefined)
  const q = useDebounce(search.trim(), 300)
  const [page, setPage] = useFilteredPage(`${q}|${source ?? ''}`)
  const query = useScreeningEntries({ q: q || undefined, source, page, page_size: ADMIN_PAGE_SIZE })
  const remove = useRemoveScreeningEntry()
  const [target, setTarget] = useState<ScreeningEntry | null>(null)

  const columns: AdminColumn<ScreeningEntry>[] = [
    {
      key: 'address',
      header: 'Address',
      mobile: 'title',
      cell: (e) => <MonoValue value={e.address} label="screened address" lead={5} tail={5} />,
    },
    {
      key: 'source',
      header: 'Source',
      mobile: 'aside',
      cell: (e) => (
        <Badge variant={e.source === 'LIST' ? 'warning' : 'outline'}>{SOURCE_LABELS[e.source]}</Badge>
      ),
    },
    {
      key: 'reason',
      header: 'Reason',
      wide: true,
      cell: (e) => <ClampedText text={e.reason} className="lg:min-w-48" />,
    },
    {
      key: 'added',
      header: 'Added',
      cell: (e) => (
        <span className="inline-flex flex-col">
          <DateCell iso={e.created_at} />
          {e.added_by && <span className="text-xs text-muted-foreground">@{e.added_by.username}</span>}
        </span>
      ),
    },
  ]
  if (canManage) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      hideHeader: true,
      className: 'text-right',
      mobile: 'actions',
      cell: (e) =>
        e.source === 'MANUAL' ? (
          <Button variant="outline" size="sm" aria-label={`Remove ${e.address}`} onClick={() => setTarget(e)}>
            <X aria-hidden /> Remove
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">From the list</span>
        ),
    })
  }

  return (
    <>
      <PagedResults
        query={query}
        skeleton="admin-screening-entries"
        label="Screened addresses"
        itemLabel="addresses"
        errorTitle="Could not load screened addresses"
        empty={{ icon: ShieldBan, title: 'No screened addresses' }}
        filtered={!!q || !!source}
        onClearFilters={() => {
          setSearch('')
          setSource(undefined)
        }}
        onPageChange={(p) => {
          setPage(p)
          scrollToTop()
        }}
        toolbar={
          <>
            <SearchField
              id="screening-entries-search"
              label="Search by address"
              value={search}
              onChange={setSearch}
              placeholder="Address"
              maxLength={56}
            />
            <FilterSelect
              id="screening-entries-source"
              label="Filter by source"
              value={source}
              onChange={setSource}
              options={SOURCES}
              labels={SOURCE_LABELS}
              allLabel="All sources"
            />
          </>
        }
      >
        {(items) => (
          <AdminTable rows={items} columns={columns} getKey={(e) => e.id} caption="Screened addresses" />
        )}
      </PagedResults>
      <ReasonDialog
        open={!!target}
        onOpenChange={(open) => !open && setTarget(null)}
        title="Remove screened address"
        description={
          target ? <span className="font-mono text-xs break-all">{target.address}</span> : undefined
        }
        label="Why is it being removed?"
        confirmLabel="Remove address"
        maxLength={500}
        pending={remove.isPending}
        onConfirm={async (note) => {
          if (!target) return
          try {
            await remove.mutateAsync({ id: target.id, note })
            toast.success('Address removed from the manual list.')
          } catch (e) {
            toast.error(errorMessage(e))
            throw e
          }
        }}
      />
    </>
  )
}

function AddEntryDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const add = useAddScreeningEntry()
  const addressId = useId()
  const reasonId = useId()
  const [address, setAddress] = useState('')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState<{ address?: string; reason?: string }>({})

  const close = (next: boolean) => {
    if (!next) {
      setAddress('')
      setReason('')
      setErrors({})
    }
    onOpenChange(next)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const value = address.trim().toUpperCase()
    const next: typeof errors = {}
    if (!/^G[A-Z2-7]{55}$/.test(value))
      next.address = 'Enter a Stellar account address (56 characters, starting with G).'
    if (reason.trim().length < 3) next.reason = 'Say why this address is screened.'
    setErrors(next)
    if (next.address || next.reason) return
    add.mutate(
      { address: value, reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success('Address added. Verifying or using it is now blocked.')
          close(false)
        },
        onError: (err) => {
          const field = isApiError(err) ? err.fieldErrors.address : undefined
          if (field) setErrors({ address: field })
          else toast.error(errorMessage(err))
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Add a screened address</DialogTitle>
            <DialogDescription>
              The address can’t be verified as a wallet, fund escrows or receive payouts. The person sees a
              neutral message; staff see this reason.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-5 space-y-4">
            <div className="space-y-2">
              <Label htmlFor={addressId}>Stellar address</Label>
              <Input
                id={addressId}
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                className="font-mono text-[0.8125rem]"
                maxLength={56}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={!!errors.address}
                aria-describedby={errors.address ? `${addressId}-error` : undefined}
              />
              {errors.address && (
                <p id={`${addressId}-error`} className="text-[0.8125rem] text-destructive">
                  {errors.address}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor={reasonId}>Reason</Label>
              <Textarea
                id={reasonId}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
                rows={3}
                aria-invalid={!!errors.reason}
                aria-describedby={errors.reason ? `${reasonId}-error` : undefined}
              />
              {errors.reason && (
                <p id={`${reasonId}-error`} className="text-[0.8125rem] text-destructive">
                  {errors.reason}
                </p>
              )}
            </div>
          </div>
          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={add.isPending}>
              {add.isPending && <LoaderCircle className="animate-spin" />}
              Add address
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function AdminScreeningPage() {
  const { data: me } = useMe()
  const canManage = hasPermission(me, 'user:manage')
  const [adding, setAdding] = useState(false)
  const [tab, setTab] = useState('blocked')
  return (
    <div className="space-y-6">
      <PageHeader
        title="Screening"
        breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Screening' }]}
        className="pb-0 lg:pb-0"
        actions={
          canManage ? (
            <Button onClick={() => setAdding(true)}>
              <Plus /> Add address
            </Button>
          ) : undefined
        }
      />
      <StatusStrip />
      <Tabs value={tab} onValueChange={setTab} className="gap-4">
        <TabsList className="h-9">
          <TabsTrigger value="blocked" className="px-3">
            Blocked attempts
          </TabsTrigger>
          <TabsTrigger value="entries" className="px-3">
            Screened addresses
          </TabsTrigger>
        </TabsList>
        <TabsContent value="blocked">
          <DecisionsList />
        </TabsContent>
        <TabsContent value="entries">
          <EntriesList canManage={canManage} />
        </TabsContent>
      </Tabs>
      <AddEntryDialog open={adding} onOpenChange={setAdding} />
    </div>
  )
}
