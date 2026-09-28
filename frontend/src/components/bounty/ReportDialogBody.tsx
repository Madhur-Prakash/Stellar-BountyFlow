import { zodResolver } from '@hookform/resolvers/zod'
import { Flag, LoaderCircle } from 'lucide-react'
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
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { useReportBounty } from '@/lib/api/queries/bounties'

const schema = z.object({
  reason: z
    .string()
    .trim()
    .min(10, 'Please describe the problem (at least 10 characters).')
    .max(2000, 'Keep it under 2,000 characters.'),
})
type Values = z.infer<typeof schema>

/** The report form. Loaded on demand by `ReportButton` (see ReportDialog.tsx). */
export default function ReportDialogBody({
  bountyId,
  open,
  onOpenChange,
}: {
  bountyId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const report = useReportBounty()
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { reason: '' } })

  const onSubmit = form.handleSubmit(({ reason }) =>
    report.mutate(
      { bountyId, reason },
      {
        onSuccess: () => {
          toast.success('Report sent to the moderators. Thank you.')
          form.reset()
          onOpenChange(false)
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    ),
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Report this bounty</DialogTitle>
          <DialogDescription>
            For scams, harmful work or misleading funding claims. Moderators review every report.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField
              control={form.control}
              name="reason"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>What’s wrong?</FormLabel>
                  <FormControl>
                    <Textarea rows={5} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="destructive" disabled={report.isPending}>
                {report.isPending ? <LoaderCircle className="animate-spin" /> : <Flag />} Send report
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
