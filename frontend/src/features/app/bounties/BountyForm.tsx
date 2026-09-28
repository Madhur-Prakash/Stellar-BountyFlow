import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle, Lock } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useForm, useWatch, type Path } from 'react-hook-form'

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
import { CATEGORIES, DIFFICULTIES, type CreateBountyRequest } from '@/lib/api/types'
import { CATEGORY_LABELS, DIFFICULTY_LABELS } from '@/lib/format'
import { applyApiErrors } from '@/lib/form-errors'
import { formatAmount, isValidAmount, multiplyAmount } from '@/lib/money'

import { bountyFormSchema, toRequest, type BountyFormValues } from './bounty-form-schema'

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
  'positions_available',
  'application_deadline',
  'completion_deadline',
  'eligibility_criteria',
  'submission_requirements',
  'acceptance_criteria',
  'repository_url',
  'links',
]

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
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-5">{children}</CardContent>
    </Card>
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
}: {
  defaultValues: BountyFormValues
  submitLabel: string
  lockEconomics?: boolean
  pending: boolean
  onSubmit: (body: CreateBountyRequest) => Promise<unknown>
}) {
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<BountyFormValues>({
    resolver: zodResolver(bountyFormSchema),
    defaultValues,
    mode: 'onTouched',
  })
  const [reward, positions, description] = useWatch({
    control: form.control,
    name: ['reward_amount', 'positions_available', 'description'],
  })
  const total =
    isValidAmount(reward) && /^\d+$/.test(positions) && Number(positions) > 0
      ? multiplyAmount(reward, Number(positions))
      : null

  const submit = form.handleSubmit(async (values) => {
    setFormError(null)
    const body = toRequest(values)
    if (lockEconomics) {
      delete (body as Partial<CreateBountyRequest>).reward_amount
      delete (body as Partial<CreateBountyRequest>).positions_available
      delete (body as Partial<CreateBountyRequest>).reward_asset
    }
    try {
      await onSubmit(body)
    } catch (e) {
      setFormError(applyApiErrors(e, form.setError, FIELDS))
    }
  })

  const textField = (
    name: Path<BountyFormValues>,
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
          {opts.description && <FormDescription>{opts.description}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  )

  return (
    <Form {...form}>
      <form onSubmit={submit} className="space-y-6" noValidate>
        <Section title="Basics" description="What needs doing, in a sentence or two.">
          {textField('title', 'Title', { placeholder: 'e.g. Add pagination to the payouts API' })}
          {textField('short_description', 'Summary', {
            rows: 2,
            description: 'Shown on marketplace cards (up to 280 characters).',
          })}
          <div className="grid gap-5 sm:grid-cols-3">
            <FormField
              control={form.control}
              name="category"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Category</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {CATEGORIES.map((c) => (
                        <SelectItem key={c} value={c}>
                          {CATEGORY_LABELS[c]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="difficulty"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Difficulty</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {DIFFICULTIES.map((d) => (
                        <SelectItem key={d} value={d}>
                          {DIFFICULTY_LABELS[d]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="visibility"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Visibility</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="PUBLIC">Public (listed in the marketplace)</SelectItem>
                      <SelectItem value="UNLISTED">Unlisted (anyone with the link)</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            {textField('required_skills', 'Required skills', {
              placeholder: 'rust, soroban',
              description: 'Comma separated.',
            })}
            {textField('tags', 'Tags', { placeholder: 'backend, api', description: 'Comma separated.' })}
          </div>
        </Section>

        <Section title="Description" description="Markdown supported. Raw HTML is not rendered.">
          <Tabs defaultValue="write">
            <TabsList>
              <TabsTrigger value="write">Write</TabsTrigger>
              <TabsTrigger value="preview">Preview</TabsTrigger>
            </TabsList>
            <TabsContent value="write" className="mt-3">
              {textField('description', 'Full description', { rows: 12 })}
            </TabsContent>
            <TabsContent value="preview" className="mt-3 min-h-40 rounded-lg border p-4">
              {description ? (
                <SafeMarkdown>{description}</SafeMarkdown>
              ) : (
                <p className="text-sm text-muted-foreground">Nothing to preview yet.</p>
              )}
            </TabsContent>
          </Tabs>
        </Section>

        <Section
          title="Reward & escrow"
          description="The reward is per position. You’ll fund reward × positions into escrow after publishing."
        >
          {lockEconomics && (
            <p className="flex items-center gap-2 rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
              <Lock className="size-4" aria-hidden /> Reward and positions can only change while the bounty is
              a draft.
            </p>
          )}
          <div className="grid gap-5 sm:grid-cols-2">
            {textField('reward_amount', 'Reward per position (XLM)', {
              inputMode: 'decimal',
              disabled: lockEconomics,
              placeholder: '250',
            })}
            {textField('positions_available', 'Positions', { inputMode: 'numeric', disabled: lockEconomics })}
          </div>
          <div className="flex items-center justify-between rounded-lg border bg-surface-raised/50 p-4">
            <span className="text-sm text-muted-foreground">Escrow required</span>
            <span className="text-lg font-semibold tabular-nums">
              {total ? `${formatAmount(total)} XLM` : '—'}
            </span>
          </div>
        </Section>

        <Section title="Timeline">
          <div className="grid gap-5 sm:grid-cols-2">
            {textField('application_deadline', 'Applications close', {
              type: 'datetime-local',
              description: 'Optional. Your local time.',
            })}
            {textField('completion_deadline', 'Work due', {
              type: 'datetime-local',
              description: 'Optional. Your local time.',
            })}
          </div>
        </Section>

        <Section title="Criteria" description="Clear criteria make reviews fair and disputes rare.">
          {textField('acceptance_criteria', 'Acceptance criteria', {
            rows: 4,
            placeholder: '- Tests pass\n- Docs updated',
          })}
          {textField('submission_requirements', 'Submission requirements', {
            rows: 3,
            placeholder: 'Link a PR and a short screen recording.',
          })}
          {textField('eligibility_criteria', 'Eligibility', { rows: 3 })}
        </Section>

        <Section title="Links">
          {textField('repository_url', 'Repository URL', { placeholder: 'https://github.com/org/repo' })}
          {textField('links', 'Other links', {
            rows: 3,
            placeholder: 'Design spec | https://…',
            description: 'One per line: "Label | URL".',
          })}
        </Section>

        <FormErrorAlert message={formError} />
        <div className="flex justify-end">
          <Button
            type="submit"
            size="lg"
            className="w-full sm:w-auto"
            disabled={pending || form.formState.isSubmitting}
          >
            {(pending || form.formState.isSubmitting) && <LoaderCircle className="animate-spin" />}
            {submitLabel}
          </Button>
        </div>
      </form>
    </Form>
  )
}
