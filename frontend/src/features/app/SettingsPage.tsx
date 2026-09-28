import { Laptop, LoaderCircle, LogOut, Moon, Sun } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { QueryView } from '@/components/layout/QueryView'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorMessage } from '@/lib/api/client'
import { useRevokeSession, useSessions } from '@/lib/api/queries/auth'
import { useNotificationPreferences, useUpdateNotificationPreferences } from '@/lib/api/queries/notifications'
import { NOTIFICATION_TYPES, type NotificationType } from '@/lib/api/types'
import { formatRelative, humanize } from '@/lib/format'
import { originOf, switchTheme } from '@/lib/theme-transition'
import { useUiPrefs, type Theme } from '@/stores/ui-prefs'

function NotificationPreferencesCard() {
  const query = useNotificationPreferences()
  const update = useUpdateNotificationPreferences()
  const save = (body: Parameters<typeof update.mutate>[0]) =>
    update.mutate(body, { onError: (e) => toast.error(errorMessage(e)) })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Notifications</CardTitle>
        <CardDescription>Choose what reaches you in the app and by email.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryView query={query} skeleton="app-settings-notifications">
          {(prefs) => (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
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
              <div className="overflow-x-auto rounded-lg border">
                <Table>
                  <caption className="sr-only">Notification preferences by type</caption>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Event</TableHead>
                      <TableHead className="text-center">In app</TableHead>
                      <TableHead className="text-center">Email</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {NOTIFICATION_TYPES.map((t: NotificationType) => {
                      const p = prefs.types[t] ?? { in_app: true, email: false }
                      return (
                        <TableRow key={t}>
                          <TableCell>{humanize(t)}</TableCell>
                          <TableCell className="text-center">
                            <Switch
                              aria-label={`${humanize(t)} in app`}
                              checked={p.in_app}
                              onCheckedChange={(v) => save({ types: { [t]: { in_app: v } } })}
                            />
                          </TableCell>
                          <TableCell className="text-center">
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
            </div>
          )}
        </QueryView>
      </CardContent>
    </Card>
  )
}

function SessionsCard() {
  const query = useSessions()
  const revoke = useRevokeSession()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Active sessions</CardTitle>
        <CardDescription>Devices signed in to your account. Revoke any you don’t recognise.</CardDescription>
      </CardHeader>
      <CardContent>
        <QueryView
          query={query}
          skeleton="app-settings-sessions"
          isEmpty={(d) => d.length === 0}
          empty={{ icon: Laptop, title: 'No active sessions' }}
        >
          {(sessions) => (
            <ul className="divide-y rounded-lg border">
              {sessions.map((s) => (
                <li
                  key={s.id}
                  className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                      <Laptop className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="truncate">{s.user_agent ?? 'Unknown device'}</span>
                      {s.is_current && <Badge variant="info">This device</Badge>}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      Signed in {formatRelative(s.created_at)}, last active {formatRelative(s.last_used_at)}
                    </div>
                  </div>
                  {!s.is_current && (
                    <Button
                      variant="ghost"
                      size="sm"
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
        </QueryView>
      </CardContent>
    </Card>
  )
}

function AppearanceCard() {
  const theme = useUiPrefs((s) => s.theme)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Appearance</CardTitle>
        <CardDescription>Stored in this browser only.</CardDescription>
      </CardHeader>
      <CardContent>
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
          <ToggleGroupItem value="light" aria-label="Light theme">
            <Sun /> Light
          </ToggleGroupItem>
          <ToggleGroupItem value="dark" aria-label="Dark theme">
            <Moon /> Dark
          </ToggleGroupItem>
        </ToggleGroup>
      </CardContent>
    </Card>
  )
}

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Settings" description="Notifications, sessions, and appearance." />
      <div className="grid gap-6">
        <NotificationPreferencesCard />
        <SessionsCard />
        <AppearanceCard />
      </div>
    </div>
  )
}
