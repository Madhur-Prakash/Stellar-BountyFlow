import { zodResolver } from '@hookform/resolvers/zod'
import { GitPullRequest, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

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
import { Textarea } from '@/components/ui/textarea'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { errorMessage, isApiError } from '@/lib/api/client'
import { useApply } from '@/lib/api/queries/applications'

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

const applySchema = z.object({
  cover_message: z
    .string()
    .trim()
    .min(30, 'Tell the requester a bit more (at least 30 characters).')
    .max(5000, 'Keep it under 5,000 characters.'),
  relevant_experience: z.string().trim().max(3000, 'Keep it under 3,000 characters.'),
  portfolio_links: z
    .string()
    .refine((v) => splitLines(v).length <= 10, 'Add at most 10 links.')
    .refine((v) => splitLines(v).every(isHttpUrl), 'Each line must be a full http(s) URL.'),
})

type ApplyValues = z.infer<typeof applySchema>

/** The application form. Loaded on demand by `ApplyDialog` (see ApplyDialog.tsx). */
export default function ApplyDialogBody({
  bountyId,
  bountyTitle,
  open,
  onOpenChange,
}: {
  bountyId: string
  bountyTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const apply = useApply(bountyId)
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ApplyValues>({
    resolver: zodResolver(applySchema),
    defaultValues: { cover_message: '', relevant_experience: '', portfolio_links: '' },
  })

  const onSubmit = form.handleSubmit((values) => {
    setFormError(null)
    apply.mutate(
      {
        cover_message: values.cover_message,
        relevant_experience: values.relevant_experience || null,
        work_samples: splitLines(values.portfolio_links),
      },
      {
        onSuccess: () => {
          toast.success('Application sent. You’ll be notified when the requester responds.')
          form.reset()
          onOpenChange(false)
        },
        onError: (e) => {
          if (isApiError(e) && e.code === 'validation_error') {
            for (const [field, message] of Object.entries(e.fieldErrors)) {
              if (field in values) form.setError(field as keyof ApplyValues, { message })
            }
          }
          setFormError(errorMessage(e))
        },
      },
    )
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Apply to this bounty</DialogTitle>
          <DialogDescription className="line-clamp-2">{bountyTitle}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField
              control={form.control}
              name="cover_message"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Proposal</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={6}
                      placeholder="How will you approach the work, and when can you deliver?"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="relevant_experience"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Relevant experience (optional)</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="portfolio_links"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Portfolio links (optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={3}
                      placeholder={'https://github.com/you/project\nhttps://your-portfolio.dev'}
                      className="font-mono text-sm"
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>One URL per line, up to 10.</FormDescription>
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
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={apply.isPending}>
                {apply.isPending ? <LoaderCircle className="animate-spin" /> : <GitPullRequest />}
                Send application
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
