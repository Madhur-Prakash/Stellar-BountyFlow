import { zodResolver } from '@hookform/resolvers/zod'
import { Bug, CircleCheck, Lightbulb, LoaderCircle, MessageSquare, ThumbsUp } from 'lucide-react'
import { useState, type ComponentType } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useLocation } from 'react-router'
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
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorMessage } from '@/lib/api/client'
import { useMe } from '@/lib/api/queries/auth'
import { useSubmitFeedback } from '@/lib/api/queries/feedback'
import { FEEDBACK_KINDS, type FeedbackKind } from '@/lib/api/types'
import { FEEDBACK_KIND_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

const MESSAGE_MIN = 10
const MESSAGE_MAX = 2000
/** The count appears once the message gets close to the limit. */
const COUNT_FROM = MESSAGE_MAX - 300

const KIND_ICONS: Record<FeedbackKind, ComponentType<{ className?: string }>> = {
  BUG: Bug,
  IDEA: Lightbulb,
  PRAISE: ThumbsUp,
  OTHER: MessageSquare,
}

const schema = z.object({
  kind: z.enum([...FEEDBACK_KINDS]),
  message: z
    .string()
    .trim()
    .min(MESSAGE_MIN, `Write at least ${MESSAGE_MIN} characters.`)
    .max(MESSAGE_MAX, `Keep it under ${MESSAGE_MAX.toLocaleString()} characters.`),
  email: z
    .string()
    .trim()
    .max(320, 'That address is too long.')
    .refine((v) => v === '' || z.email().safeParse(v).success, 'Enter a valid email address.'),
})
type Values = z.infer<typeof schema>

/**
 * The feedback form, in a dialog. Loaded on demand by `FeedbackLauncher`, so none of this is in the first
 * bundle. Radix traps focus while it is open and hands focus back to the button that opened it.
 */
export default function FeedbackDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { data: me } = useMe()
  const { pathname } = useLocation()
  const submit = useSubmitFeedback()
  const [sent, setSent] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { kind: 'BUG', message: '', email: '' },
  })
  const message = useWatch({ control: form.control, name: 'message' })

  const onSubmit = form.handleSubmit((values) => {
    setFormError(null)
    submit.mutate(
      {
        kind: values.kind,
        message: values.message,
        email: me || !values.email ? null : values.email,
        path: pathname,
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
      },
      { onSuccess: () => setSent(true), onError: (e) => setFormError(errorMessage(e)) },
    )
  })

  return (
    <Dialog open={open} onOpenChange={(next) => !submit.isPending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        {sent ? (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <CircleCheck className="size-4 text-success" aria-hidden />
                Thanks — this reached the maintainer
              </DialogTitle>
              <DialogDescription>Sent with the page you were on and your browser details.</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button type="button" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Send feedback</DialogTitle>
              <DialogDescription>
                {me
                  ? `Sent from your account, ${me.email}.`
                  : 'Tell the maintainer what is wrong, missing or working well.'}
              </DialogDescription>
            </DialogHeader>

            <Form {...form}>
              <form onSubmit={onSubmit} className="space-y-4" noValidate>
                <FormField
                  control={form.control}
                  name="kind"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Type</FormLabel>
                      <FormControl>
                        <ToggleGroup
                          type="single"
                          variant="outline"
                          value={field.value}
                          onValueChange={(v) => v && field.onChange(v as FeedbackKind)}
                          aria-label="Type of feedback"
                          className="w-full"
                        >
                          {FEEDBACK_KINDS.map((kind) => {
                            const Icon = KIND_ICONS[kind]
                            return (
                              <ToggleGroupItem key={kind} value={kind} className="flex-1 px-2">
                                <Icon aria-hidden />
                                {FEEDBACK_KIND_LABELS[kind]}
                              </ToggleGroupItem>
                            )
                          })}
                        </ToggleGroup>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="message"
                  render={({ field }) => (
                    <FormItem>
                      <div className="flex items-baseline justify-between gap-3">
                        <FormLabel>Message</FormLabel>
                        {/* The region stays mounted so the count is announced when it appears. */}
                        <span
                          aria-live="polite"
                          className={cn(
                            'font-mono text-xs tabular-nums',
                            message.length > MESSAGE_MAX ? 'text-destructive' : 'text-muted-foreground',
                          )}
                        >
                          {message.length >= COUNT_FROM
                            ? `${message.length.toLocaleString()}/${MESSAGE_MAX.toLocaleString()}`
                            : ''}
                        </span>
                      </div>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={5}
                          autoFocus
                          maxLength={MESSAGE_MAX + 1}
                          placeholder="What happened, or what would you change?"
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {!me && (
                  <FormField
                    control={form.control}
                    name="email"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          Email <span className="font-normal text-muted-foreground">(optional)</span>
                        </FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="email"
                            inputMode="email"
                            autoComplete="email"
                            placeholder="you@example.com"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                <p className="rounded-md bg-surface px-3 py-2.5 text-xs leading-5 text-muted-foreground">
                  Sent with your note: the page you are on (
                  <span className="font-mono break-all">{pathname}</span>), your window size and your
                  browser’s user agent. Nothing you typed on the page, and no wallet address.
                </p>

                {formError && (
                  <p role="alert" className="text-sm text-destructive">
                    {formError}
                  </p>
                )}

                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={submit.isPending}
                    onClick={() => onOpenChange(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={submit.isPending}>
                    {submit.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
                    Send
                  </Button>
                </DialogFooter>
              </form>
            </Form>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
