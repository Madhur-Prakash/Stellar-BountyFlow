import { Laptop, LoaderCircle, LogOut, Moon, Sun } from 'lucide-react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorMessage } from '@/lib/api/client'
import { useRevokeSession, useSessions } from '@/lib/api/queries/auth'
import { useNotificationPreferences, useUpdateNotificationPreferences } from '@/lib/api/queries/notifications'
import { NOTIFICATION_TYPES, type NotificationType } from '@/lib/api/types'
import { formatDateTime, formatRelative, humanize } from '@/lib/format'
import { originOf, switchTheme } from '@/lib/theme-transition'
import { describeUserAgent } from '@/lib/user-agent'
import { useUiPrefs, type Theme } from '@/stores/ui-prefs'

import { AccountLayout } from './AccountNav'
import { CardQuery } from './workspace-ui'

/** One settings card: a header row, flush content, and an optional footer. */
function SettingsSection({
  id,
  title,
  description,
  footer,
  children,
}: {
  id: string
  title: string
  description?: ReactNode
  footer?: ReactNode
  children: ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-h`}>
      <Card className="gap-0 pb-0">
        <CardHeader className="pb-5">
          <CardTitle>
            <h2 id={`${id}-h`}>{title}</h2>
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        {children}
        {footer && (
          <CardFooter className="px-5 py-3 text-[0.8125rem] text-muted-foreground">{footer}</CardFooter>
        )}
      </Card>
    </section>
  )
}

function NotificationPreferencesCard() {
  const query = useNotificationPreferences()
  const update = useUpdateNotificationPreferences()
  const save = (body: Parameters<typeof update.mutate>[0]) =>
    update.mutate(body, { onError: (e) => toast.error(errorMessage(e)) })

  return (
    <SettingsSection
      id="notifications"
      title="Notifications"
      description="Choose what reaches you in the app and by email."
      footer={
        <span className="inline-flex items-center gap-2">
          {update.isPending && <LoaderCircle className="size-3.5 animate-spin" aria-hidden />}
          Changes save as you make them.
        </span>
      }
    >
      <div className="border-t">
        <CardQuery query={query} skeleton="app-settings-notifications" rows={6}>
          {(prefs) => (
            <>
              <div className="flex items-center justify-between gap-4 px-5 py-4">
                <Label htmlFor="email-enabled" className="flex-col items-start gap-0.5">
                  <span>Email notifications</span>
                  <span className="text-xs font-normal text-muted-foreground">
                    Master switch for all notification emails
                  </span>
                </Label>
                <Switch
                  id="email-enabled"
                  checked={prefs.email_enabled}
                  onCheckedChange={(v) => save({ email_enabled: v })}
                />
              </div>
              <div className="border-t">
                <Table>
                  <caption className="sr-only">Notification preferences by type</caption>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-5">Event</TableHead>
                      <TableHead className="w-24 text-center">In app</TableHead>
                      <TableHead className="w-24 pr-5 text-center">Email</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {NOTIFICATION_TYPES.map((t: NotificationType) => {
                      const p = prefs.types[t] ?? { in_app: true, email: false }
                      return (
                        <TableRow key={t}>
                          <TableCell className="pl-5">{humanize(t)}</TableCell>
                          <TableCell className="text-center">
                            <Switch
                              aria-label={`${humanize(t)} in app`}
                              checked={p.in_app}
                              onCheckedChange={(v) => save({ types: { [t]: { in_app: v } } })}
                            />
                          </TableCell>
                          <TableCell className="pr-5 text-center">
                            <Switch
                              aria-label={`${humanize(t)} by email`}
                              checked={p.email}
                              disabled={!prefs.email_enabled}
                              onCheckedChange={(v) => save({ types: { [t]: { email: v } } })}
                            />
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardQuery>
      </div>
    </SettingsSection>
  )
}

function SessionsCard() {
  const query = useSessions()
  const revoke = useRevokeSession()
  return (
    <SettingsSection
      id="sessions"
      title="Active sessions"
      description="Devices signed in to your account. Revoke any you don’t recognise."
    >
      <div className="border-t">
        <CardQuery
          query={query}
          skeleton="app-settings-sessions"
          rows={3}
          isEmpty={(d) => d.length === 0}
          empty={{ icon: Laptop, title: 'No active sessions' }}
        >
          {(sessions) => (
            <ul className="divide-y">
              {sessions.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-3.5 sm:px-5">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border bg-surface text-muted-foreground">
                      <Laptop className="size-4" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2 text-sm">
                        <span className="truncate font-medium" title={s.user_agent ?? undefined}>
                          {describeUserAgent(s.user_agent)}
                        </span>
                        {s.is_current && (
                          <Badge variant="info" className="shrink-0">
                            This device
                          </Badge>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        Signed in{' '}
                        <time dateTime={s.created_at} title={formatDateTime(s.created_at)}>
                          {formatRelative(s.created_at)}
                        </time>
                        , last active{' '}
                        <time dateTime={s.last_used_at ?? undefined} title={formatDateTime(s.last_used_at)}>
                          {formatRelative(s.last_used_at)}
                        </time>
                      </div>
                    </div>
                  </div>
                  {!s.is_current && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0"
                      disabled={revoke.isPending}
                      onClick={() =>
                        revoke.mutate(s.id, {
                          onSuccess: () => toast.success('Session revoked'),
                          onError: (e) => toast.error(errorMessage(e)),
                        })
                      }
                    >
                      {revoke.isPending && revoke.variables === s.id ? (
                        <LoaderCircle className="animate-spin" />
                      ) : (
                        <LogOut />
                      )}
                      Revoke
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardQuery>
      </div>
    </SettingsSection>
  )
}

function AppearanceCard() {
  const theme = useUiPrefs((s) => s.theme)
  return (
    <SettingsSection id="appearance" title="Appearance" description="Stored in this browser only.">
      <CardContent className="border-t py-5">
        <ToggleGroup
          type="single"
          variant="outline"
          value={theme}
          onValueChange={(v) =>
            v &&
            switchTheme(
              v as Theme,
              originOf(document.querySelector(`[aria-label="${v === 'dark' ? 'Dark' : 'Light'} theme"]`)),
            )
          }
          aria-label="Theme"
        >
          <ToggleGroupItem value="light" aria-label="Light theme" className="px-3">
            <Sun /> Light
          </ToggleGroupItem>
          <ToggleGroupItem value="dark" aria-label="Dark theme" className="px-3">
            <Moon /> Dark
          </ToggleGroupItem>
        </ToggleGroup>
      </CardContent>
    </SettingsSection>
  )
}

export default function SettingsPage() {
  return (
    <div className="lg:max-w-252">
      <PageHeader title="Settings" />
      <AccountLayout>
        <NotificationPreferencesCard />
        <SessionsCard />
        <AppearanceCard />
      </AccountLayout>
    </div>
  )
}
