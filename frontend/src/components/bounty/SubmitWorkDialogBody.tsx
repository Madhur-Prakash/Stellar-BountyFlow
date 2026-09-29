import { zodResolver } from '@hookform/resolvers/zod'
import { FileCheck2, LoaderCircle, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { isPullRequestUrl } from '@/components/github/pr-display'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage, isApiError } from '@/lib/api/client'
import { useCreateSubmission, useUpdateSubmission } from '@/lib/api/queries/submissions'
import { MAX_PULL_REQUESTS, type Milestone, type Submission } from '@/lib/api/types'
import { formatAmount } from '@/lib/money'

const splitLines = (v: string) =>
  v
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean)

const isHttpUrl = (s: string) => {
  try {
    const u = new URL(s)
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}

const schema = z.object({
  /** Milestone bounties: the milestone this work is for. */
  milestone_id: z.string(),
  description: z
    .string()
    .trim()
    .min(20, 'Describe what you delivered (at least 20 characters).')
    .max(20_000, 'Keep it under 20,000 characters.'),
  evidence_url: z
    .string()
    .trim()
    .refine((v) => v === '' || isHttpUrl(v), 'Use a full http(s) URL, e.g. a pull request.'),
  evidence_links: z
    .string()
    .refine((v) => splitLines(v).length <= 10, 'Add at most 10 links.')
    .refine((v) => splitLines(v).every(isHttpUrl), 'Each line must be a full http(s) URL.'),
  pull_request_urls: z
    .string()
    .refine((v) => splitLines(v).length <= MAX_PULL_REQUESTS, `Link at most ${MAX_PULL_REQUESTS} pull requests.`)
    .refine(
      (v) => splitLines(v).every(isPullRequestUrl),
      'Each line must be a GitHub pull request URL, like https://github.com/owner/repo/pull/123.',
    ),
})

type Values = z.infer<typeof schema>

/**
 * Deliver work for an assigned bounty (create), or send a new version after
 * the requester asked for changes (revise → PATCH, status RESUBMITTED).
 * Loaded on demand by `SubmitWorkDialog` (see SubmitWorkDialog.tsx).
 */
export default function SubmitWorkDialogBody({
  open,
  onOpenChange,
  bountyId,
  bountyTitle,
  submission,
  milestones = [],
  assetCode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  bountyId: string
  bountyTitle: string
  /** Present in revise mode. */
  submission?: Submission | null
  /** Milestone bounties: the open milestones this contributor can still deliver. */
  milestones?: Milestone[]
  assetCode?: string
}) {
  const revising = !!submission
  const pickMilestone = !revising && milestones.length > 0
  const create = useCreateSubmission(bountyId)
  const update = useUpdateSubmission()
  const pending = create.isPending || update.isPending
  const [formError, setFormError] = useState<string | null>(null)

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    values: {
      milestone_id: milestones.length === 1 ? milestones[0].id : '',
      description: submission?.description ?? '',
      evidence_url: submission?.evidence_url ?? '',
      evidence_links: (submission?.evidence_links ?? []).join('\n'),
      pull_request_urls: (submission?.pull_requests ?? []).map((pr) => pr.url).join('\n'),
    },
    resetOptions: { keepDirtyValues: true },
  })

  const onSubmit = form.handleSubmit((values) => {
    if (pending) return
    setFormError(null)
    if (pickMilestone && !values.milestone_id) {
      form.setError('milestone_id', { message: 'Choose the milestone this work is for.' })
      return
    }
    const body = {
      ...(pickMilestone ? { milestone_id: values.milestone_id } : {}),
      description: values.description,
      evidence_url: values.evidence_url || null,
      evidence_links: splitLines(values.evidence_links),
      pull_request_urls: splitLines(values.pull_request_urls),
    }
    const onError = (e: unknown) => {
      if (isApiError(e) && e.code === 'validation_error') {
        for (const [field, message] of Object.entries(e.fieldErrors)) {
          const key = field.split('.')[0]
          if (key in values) form.setError(key as keyof Values, { message })
        }
      }
      setFormError(errorMessage(e))
    }
    const onSuccess = () => {
      toast.success(revising ? 'Revision sent for review' : 'Work submitted for review')
      form.reset()
      onOpenChange(false)
    }
    if (revising && submission) update.mutate({ id: submission.id, body }, { onSuccess, onError })
    else create.mutate(body, { onSuccess, onError })
  })

  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{revising ? 'Send a revised version' : 'Submit your work'}</DialogTitle>
          <DialogDescription className="line-clamp-2">
            {revising && submission?.milestone
              ? `${bountyTitle}, milestone ${submission.milestone.position + 1}: ${submission.milestone.title}`
              : bountyTitle}
          </DialogDescription>
        </DialogHeader>
        {revising && submission?.review_feedback && (
          <Alert variant="info">
            <AlertDescription>
              <span className="font-medium text-foreground">Requested changes: </span>
              {submission.review_feedback}
            </AlertDescription>
          </Alert>
        )}
        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            {pickMilestone && (
              <FormField
                control={form.control}
                name="milestone_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Milestone</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="Choose a milestone" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {milestones.map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            {m.position + 1}. {m.title} ({formatAmount(m.amount)}
                            {assetCode ? ` ${assetCode}` : ''})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>Approving this work pays that milestone.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>What you delivered</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={7}
                      placeholder="What you delivered and how to check it against the acceptance criteria."
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>Markdown supported.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="evidence_url"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Primary evidence link (optional)</FormLabel>
                  <FormControl>
                    <Input
                      type="url"
                      inputMode="url"
                      placeholder="https://github.com/org/repo/pull/123"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="evidence_links"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>More links (optional)</FormLabel>
                  <FormControl>
                    <Textarea rows={3} className="font-mono text-sm" placeholder="https://…" {...field} />
                  </FormControl>
                  <FormDescription>One URL per line, up to 10.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="pull_request_urls"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Pull requests (optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={2}
                      className="font-mono text-sm"
                      placeholder="https://github.com/owner/repo/pull/123"
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    One per line, up to {MAX_PULL_REQUESTS}. Each is checked with GitHub: the repository, that you
                    opened it, its state and its checks.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            {formError && (
              <Alert variant="destructive">
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {pending ? (
                  <LoaderCircle className="animate-spin" />
                ) : revising ? (
                  <RotateCcw />
                ) : (
                  <FileCheck2 />
                )}
                {revising ? 'Send revision' : 'Submit work'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
