import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, Lock } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useForm, useWatch, type Control, type FieldPathByValue, type Path } from 'react-hook-form'
import { Link } from 'react-router'

import { BountyStatusBadge } from '@/components/bounty/BountyStatusBadge'
import { MetaList } from '@/components/bounty/MetaList'
import { SkillTags } from '@/components/bounty/SkillTags'
import { SafeMarkdown } from '@/components/markdown/SafeMarkdown'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { FormErrorAlert } from '@/features/auth/AuthCard'
import { CATEGORIES, DIFFICULTIES, type BountyStatus, type CreateBountyRequest } from '@/lib/api/types'
import { CATEGORY_LABELS, DIFFICULTY_LABELS, formatDate } from '@/lib/format'
import { applyApiErrors } from '@/lib/form-errors'
import { formatAmount, isValidAmount, multiplyAmount } from '@/lib/money'

import { useAssetCode } from '../assets/asset-display'
import { RewardAssetSelect } from '../assets/RewardAssetSelect'
import { bountyFormSchema, localInputToIso, toRequest, type BountyFormValues } from './bounty-form-schema'
import { MilestonesEditor, ReviewWindowField } from './EscrowTermsFields'

const FIELDS: Path<BountyFormValues>[] = [
  'title',
  'short_description',
  'description',
  'category',
  'difficulty',
  'visibility',
  'tags',
  'required_skills',
  'reward_amount',
  'reward_asset',
  'positions_available',
  'application_deadline',
  'completion_deadline',
  'eligibility_criteria',
  'submission_requirements',
  'acceptance_criteria',
  'repository_url',
  'links',
  'milestones',
]

const HELP = 'text-[0.8125rem]'

function Section({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-5">{children}</CardContent>
    </Card>
  )
}

const csvList = (v: string) =>
  Array.from(
    new Set(
      v
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
    ),
  )

/** How the bounty will read on a marketplace card, from what has been typed so far. */
function LivePreview({ control, status }: { control: Control<BountyFormValues>; status: BountyStatus }) {
  const [title, summary, category, difficulty, skills, reward, positions, closes, rewardAsset] = useWatch({
    control,
    name: [
      'title',
      'short_description',
      'category',
      'difficulty',
      'required_skills',
      'reward_amount',
      'positions_available',
      'application_deadline',
      'reward_asset',
    ],
  })
  const code = useAssetCode(rewardAsset)
  const count = /^\d+$/.test(positions) ? Number(positions) : 0
  const closesIso = localInputToIso(closes)
  return (
    <aside aria-label="Live preview" className="hidden xl:block">
      <div className="sticky top-20 space-y-2">
        <p className="px-1 text-xs font-medium text-muted-foreground">Preview</p>
        <div className="rounded-xl border bg-card p-5 shadow-soft">
          <BountyStatusBadge status={status} />
          <p className="mt-2.5 text-[0.9375rem] leading-snug font-semibold wrap-break-word">
            {title.trim() || <span className="text-muted-foreground">Untitled bounty</span>}
          </p>
          {summary.trim() && (
            <p className="mt-1 line-clamp-3 text-sm wrap-break-word text-muted-foreground">{summary}</p>
          )}
          <MetaList className="mt-3">
            <span>{CATEGORY_LABELS[category]}</span>
            <span>{DIFFICULTY_LABELS[difficulty]}</span>
          </MetaList>
          <SkillTags skills={csvList(skills)} max={3} className="mt-3" label="Skills" />
          <div className="mt-4 border-t pt-4 text-sm">
            {isValidAmount(reward) ? (
              <p>
                <span className="amount text-lg">{formatAmount(reward)}</span>{' '}
                <span className="text-muted-foreground">{code} per position</span>
              </p>
            ) : (
              <p className="text-muted-foreground">No reward set</p>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              {count === 1 ? '1 position' : `${count} positions`}
              {closesIso ? `, applications close ${formatDate(closesIso)}` : ''}
            </p>
          </div>
        </div>
      </div>
    </aside>
  )
}

/**
 * Shared create / edit form. `lockEconomics` disables reward and positions
 * (the API only allows changing them while the bounty is a DRAFT).
 */
export function BountyForm({
  defaultValues,
  submitLabel,
  lockEconomics = false,
  pending,
  onSubmit,
  cancelTo,
  footerNote,
  status = 'DRAFT',
}: {
  defaultValues: BountyFormValues
  submitLabel: string
  lockEconomics?: boolean
  pending: boolean
  onSubmit: (body: CreateBountyRequest) => Promise<unknown>
  /** Where "Cancel" goes. */
  cancelTo?: string
  /** Short line beside the actions in the sticky footer. */
  footerNote?: string
  /** Current status, shown on the preview card. */
  status?: BountyStatus
}) {
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<BountyFormValues>({
    resolver: zodResolver(bountyFormSchema),
    defaultValues,
    mode: 'onTouched',
  })
  const [reward, positions, description, rewardAsset] = useWatch({
    control: form.control,
    name: ['reward_amount', 'positions_available', 'description', 'reward_asset'],
  })
  const code = useAssetCode(rewardAsset)
  const total =
    isValidAmount(reward) && /^\d+$/.test(positions) && Number(positions) > 0
      ? multiplyAmount(reward, Number(positions))
      : null
  const busy = pending || form.formState.isSubmitting

  const submit = form.handleSubmit(async (values) => {
    setFormError(null)
    const body = toRequest(values)
    if (lockEconomics) {
      delete (body as Partial<CreateBountyRequest>).reward_amount
      delete (body as Partial<CreateBountyRequest>).positions_available
      delete (body as Partial<CreateBountyRequest>).reward_asset
      // Milestones are part of the reward terms, which are fixed once the bounty is published.
      delete (body as Partial<CreateBountyRequest>).milestones
    }
    try {
      await onSubmit(body)
    } catch (e) {
      setFormError(applyApiErrors(e, form.setError, FIELDS))
    }
  })

  const textField = (
    name: FieldPathByValue<BountyFormValues, string>,
    label: string,
    opts: {
      description?: string
      placeholder?: string
      rows?: number
      type?: string
      disabled?: boolean
      inputMode?: 'decimal' | 'numeric'
    } = {},
  ) => (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            {opts.rows ? (
              <Textarea rows={opts.rows} placeholder={opts.placeholder} {...field} />
            ) : (
              <Input
                type={opts.type}
                placeholder={opts.placeholder}
                disabled={opts.disabled}
                inputMode={opts.inputMode}
                {...field}
              />
            )}
          </FormControl>
          {opts.description && <FormDescription className={HELP}>{opts.description}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  )

  const selectField = (
    name: 'category' | 'difficulty' | 'visibility',
    label: string,
    options: { value: string; label: string }[],
  ) => (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem className="min-w-0">
          <FormLabel>{label}</FormLabel>
          <Select value={field.value} onValueChange={field.onChange}>
            <FormControl>
              <SelectTrigger className="w-full min-w-0 *:data-[slot=select-value]:block *:data-[slot=select-value]:truncate">
                <SelectValue />
              </SelectTrigger>
            </FormControl>
            <SelectContent>
              {options.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FormMessage />
        </FormItem>
      )}
    />
  )

  return (
    <Form {...form}>
      <form onSubmit={submit} className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_18rem]" noValidate>
        <div className="min-w-0 space-y-6">
          <Section title="Basics">
            {textField('title', 'Title', { placeholder: 'e.g. Add pagination to the payouts API' })}
            {textField('short_description', 'Summary', {
              rows: 2,
              description: 'Shown on marketplace cards. Up to 280 characters.',
            })}
            <div className="grid gap-5 sm:grid-cols-3">
              {selectField(
                'category',
                'Category',
                CATEGORIES.map((c) => ({ value: c, label: CATEGORY_LABELS[c] })),
              )}
              {selectField(
                'difficulty',
                'Difficulty',
                DIFFICULTIES.map((d) => ({ value: d, label: DIFFICULTY_LABELS[d] })),
              )}
              {selectField('visibility', 'Visibility', [
                { value: 'PUBLIC', label: 'Public (listed in the marketplace)' },
                { value: 'UNLISTED', label: 'Unlisted (anyone with the link)' },
              ])}
            </div>
          </Section>

          <Section title="Scope and criteria">
            <Tabs defaultValue="write" className="gap-3">
              <TabsList>
                <TabsTrigger value="write" className="px-3">
                  Write
                </TabsTrigger>
                <TabsTrigger value="preview" className="px-3">
                  Preview
                </TabsTrigger>
              </TabsList>
              <TabsContent value="write">
                {textField('description', 'Full description', {
                  rows: 12,
                  description: 'Markdown supported.',
                })}
              </TabsContent>
              <TabsContent value="preview" className="min-h-40 rounded-lg border bg-surface/40 p-4">
                {description ? (
                  <SafeMarkdown>{description}</SafeMarkdown>
                ) : (
                  <p className="text-sm text-muted-foreground">Nothing to preview yet.</p>
                )}
              </TabsContent>
            </Tabs>
            {textField('acceptance_criteria', 'Acceptance criteria', {
              rows: 4,
              placeholder: '- Tests pass\n- Docs updated',
            })}
            {textField('submission_requirements', 'Submission requirements', {
              rows: 3,
              placeholder: 'Link a PR and a short screen recording.',
            })}
          </Section>

          <Section title="Reward and positions">
            {lockEconomics && (
              <p className="flex items-center gap-2 rounded-lg border bg-surface/60 px-3 py-2.5 text-sm text-muted-foreground">
                <Lock className="size-4 shrink-0" aria-hidden /> Reward and positions can only change while
                the bounty is a draft.
              </p>
            )}
            <div className="grid gap-5 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="reward_asset"
                render={({ field }) => (
                  <FormItem className="min-w-0 sm:col-span-2">
                    <FormLabel>Reward asset</FormLabel>
                    <FormControl>
                      <RewardAssetSelect
                        value={field.value}
                        onChange={field.onChange}
                        disabled={lockEconomics}
                      />
                    </FormControl>
                    <FormDescription className={HELP}>
                      Contributors need a trustline for assets other than XLM before they can be paid.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {textField('reward_amount', `Reward per position (${code})`, {
                inputMode: 'decimal',
                disabled: lockEconomics,
                placeholder: '250',
              })}
              {textField('positions_available', 'Positions', {
                inputMode: 'numeric',
                disabled: lockEconomics,
              })}
            </div>
            <div className="flex items-center justify-between gap-3 rounded-lg border bg-surface/60 px-4 py-3">
              <span className="text-sm text-muted-foreground">Escrow required</span>
              <span className="amount text-base">{total ? `${formatAmount(total)} ${code}` : '—'}</span>
            </div>
            <MilestonesEditor control={form.control} disabled={lockEconomics} code={code} />
          </Section>

          <Section title="Timeline">
            <div className="grid gap-5 sm:grid-cols-2">
              {textField('application_deadline', 'Applications close', {
                type: 'datetime-local',
                description: 'Optional, in your local time.',
              })}
              {textField('completion_deadline', 'Work due', {
                type: 'datetime-local',
                description: 'Optional, in your local time.',
              })}
            </div>
            <ReviewWindowField control={form.control} />
          </Section>

          <Section title="Skills and eligibility">
            <div className="grid gap-5 sm:grid-cols-2">
              {textField('required_skills', 'Required skills', {
                placeholder: 'rust, soroban',
                description: 'Comma separated.',
              })}
              {textField('tags', 'Tags', { placeholder: 'backend, api', description: 'Comma separated.' })}
            </div>
            {textField('eligibility_criteria', 'Eligibility', { rows: 3 })}
          </Section>

          <Section title="Links">
            {textField('repository_url', 'Repository URL', { placeholder: 'https://github.com/org/repo' })}
            {textField('links', 'Other links', {
              rows: 3,
              placeholder: 'Design spec | https://…',
              description: 'One per line, as "Label | URL".',
            })}
          </Section>

          <FormErrorAlert message={formError} />
        </div>

        <LivePreview control={form.control} status={status} />

        <div className="sticky bottom-3 z-10 flex flex-col-reverse gap-3 rounded-xl border bg-card/95 px-4 py-3 shadow-lift backdrop-blur supports-backdrop-filter:bg-card/85 sm:flex-row sm:items-center sm:justify-between xl:col-span-2">
          <p className="hidden text-[0.8125rem] text-muted-foreground sm:block">{footerNote}</p>
          <div className="flex gap-2">
            {cancelTo && (
              <Button asChild variant="ghost" className="flex-1 sm:flex-none">
                <Link to={cancelTo}>Cancel</Link>
              </Button>
            )}
            <Button type="submit" className="flex-1 sm:flex-none" disabled={busy}>
              {busy && <LoaderCircle className="animate-spin" />}
              {submitLabel}
            </Button>
          </div>
        </div>
      </form>
    </Form>
  )
}
