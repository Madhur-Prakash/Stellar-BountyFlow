import { useId } from 'react'
import { Link } from 'react-router'

import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useNotificationPreferences } from '@/lib/api/queries/notifications'
import { ALERT_FREQUENCIES, type AlertFrequency } from '@/lib/api/types'

import { FREQUENCY_LABELS } from './saved-search-params'

export type AlertSettings = { alert_frequency: AlertFrequency; notify_in_app: boolean; notify_email: boolean }

const HINTS: Record<AlertFrequency, string> = {
  INSTANT: 'As soon as a matching bounty is published or funded.',
  DAILY: 'One summary a day with the new matches.',
  WEEKLY: 'One summary every Monday with the new matches.',
  OFF: 'No alerts. New matches still show on the saved search.',
}

/** How and when a saved search alerts: frequency plus the in-app and email channels. */
export function AlertSettingsFields({
  value,
  onChange,
}: {
  value: AlertSettings
  onChange: (patch: Partial<AlertSettings>) => void
}) {
  const id = useId()
  const prefs = useNotificationPreferences()
  const off = value.alert_frequency === 'OFF'
  const emailBlocked = prefs.data ? !prefs.data.email_enabled : false
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={`${id}-frequency`}>Alerts</Label>
        <Select
          value={value.alert_frequency}
          onValueChange={(v) => onChange({ alert_frequency: v as AlertFrequency })}
        >
          <SelectTrigger id={`${id}-frequency`} className="w-full" aria-describedby={`${id}-hint`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ALERT_FREQUENCIES.map((f) => (
              <SelectItem key={f} value={f}>
                {FREQUENCY_LABELS[f]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {HINTS[value.alert_frequency]}
        </p>
      </div>
      <fieldset className="space-y-2.5" disabled={off}>
        <legend className="mb-2 text-sm font-medium">Send alerts</legend>
        <div className="flex min-h-9 items-center justify-between gap-3">
          <Label htmlFor={`${id}-in-app`} className="font-normal">
            In the app
          </Label>
          <Switch
            id={`${id}-in-app`}
            checked={value.notify_in_app && !off}
            disabled={off}
            onCheckedChange={(v) => onChange({ notify_in_app: v })}
          />
        </div>
        <div className="flex min-h-9 items-center justify-between gap-3">
          <Label htmlFor={`${id}-email`} className="font-normal">
            By email
          </Label>
          <Switch
            id={`${id}-email`}
            checked={value.notify_email && !off}
            disabled={off}
            onCheckedChange={(v) => onChange({ notify_email: v })}
          />
        </div>
        {emailBlocked && value.notify_email && !off && (
          <p className="text-xs text-muted-foreground">
            Email notifications are off in your{' '}
            <Link to="/app/settings" className="font-medium text-primary-emphasis hover:underline">
              settings
            </Link>
            , so only in-app alerts will arrive.
          </p>
        )}
      </fieldset>
    </div>
  )
}
