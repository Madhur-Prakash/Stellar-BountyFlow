import { zodResolver } from '@hookform/resolvers/zod'
import { Flag, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useLocation, useNavigate } from 'react-router'
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
import { useMe } from '@/lib/api/queries/auth'
import { useReportBounty } from '@/lib/api/queries/bounties'
import { loginPath } from '@/lib/auth-redirect'

const schema = z.object({
  reason: z
    .string()
    .trim()
    .min(10, 'Please describe the problem (at least 10 characters).')
    .max(2000, 'Keep it under 2,000 characters.'),
})
type Values = z.infer<typeof schema>

export function ReportButton({ bountyId }: { bountyId: string }) {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const report = useReportBounty()
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { reason: '' } })

  const onSubmit = form.handleSubmit(({ reason }) =>
    report.mutate(
      { bountyId, reason },
      {
        onSuccess: () => {
          toast.success('Report sent to the moderators. Thank you.')
          form.reset()
          setOpen(false)
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    ),
  )

  return (
    <>
      <Button
        variant="ghost"
        onClick={() => (me ? setOpen(true) : navigate(loginPath(`${location.pathname}${location.search}`)))}
        className="text-muted-foreground"
      >
        <Flag /> Report
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Report this bounty</DialogTitle>
            <DialogDescription>
              Reports go to BountyFlow moderators. Use this for scams, illegal or harmful work, or misleading
              funding claims.
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
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
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
    </>
  )
}
