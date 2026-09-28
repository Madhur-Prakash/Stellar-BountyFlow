import { Bell, CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { errorMessage } from '@/lib/api/client'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from '@/lib/api/queries/notifications'
import type { Notification } from '@/lib/api/types'
import { formatDateTime, formatRelative, humanize } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Only in-app relative links are followed from notification payloads. */
const internalLink = (link: string | null) =>
  link && link.startsWith('/') && !link.startsWith('//') ? link : null

function NotificationRow({ n }: { n: Notification }) {
  const markRead = useMarkNotificationRead()
  const unread = !n.read_at
  const link = internalLink(n.link)
  const onOpen = () => {
    if (unread) markRead.mutate(n.id)
  }
  return (
    <li className={cn('flex gap-4 p-4', unread && 'bg-primary/[0.04]')}>
      <span
        className={cn('mt-2 size-2 shrink-0 rounded-full', unread ? 'bg-primary' : 'bg-transparent')}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-medium">
            {link ? (
              <Link to={link} onClick={onOpen} className="hover:underline">
                {n.title}
              </Link>
            ) : (
              n.title
            )}
            {unread && <span className="sr-only"> (unread)</span>}
          </h3>
          <time
            dateTime={n.created_at}
            title={formatDateTime(n.created_at)}
            className="text-xs text-muted-foreground"
          >
            {formatRelative(n.created_at)}
          </time>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{n.message}</p>
        <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
          <span>{humanize(n.notification_type)}</span>
          {unread && (
            <Button
              variant="ghost"
              size="xs"
              onClick={() => markRead.mutate(n.id, { onError: (e) => toast.error(errorMessage(e)) })}
              disabled={markRead.isPending}
            >
              Mark as read
            </Button>
          )}
        </div>
      </div>
    </li>
  )
}

export default function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [page, setPage] = useState(1)
  const query = useNotifications({ unread_only: unreadOnly, page, page_size: 20 })
  const markAll = useMarkAllNotificationsRead()

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Notifications"
        description={
          query.data
            ? `${query.data.unread_count} unread`
            : 'Updates about your bounties, applications, and payouts.'
        }
        actions={
          <Button
            variant="outline"
            disabled={markAll.isPending || !query.data?.unread_count}
            onClick={() =>
              markAll.mutate(undefined, {
                onSuccess: () => toast.success('All notifications marked as read'),
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            <CheckCheck /> Mark all read
          </Button>
        }
      />
      <Tabs
        value={unreadOnly ? 'unread' : 'all'}
        onValueChange={(v) => {
          setUnreadOnly(v === 'unread')
          setPage(1)
        }}
        className="mb-4"
      >
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="unread">Unread</TabsTrigger>
        </TabsList>

        <TabsContent value={unreadOnly ? 'unread' : 'all'}>
          <QueryView
            query={query}
            skeleton="app-notifications"
            isEmpty={(d) => d.items.length === 0}
            empty={{
              icon: Bell,
              title: unreadOnly ? 'You’re all caught up' : 'No notifications yet',
              description: 'We’ll let you know when something needs your attention.',
            }}
          >
            {(data) => (
              <>
                <ul className="divide-y overflow-hidden rounded-xl border bg-card shadow-soft">
                  {data.items.map((n) => (
                    <NotificationRow key={n.id} n={n} />
                  ))}
                </ul>
                <PaginationBar
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  pageSize={data.page_size}
                  onPageChange={setPage}
                  itemLabel="notifications"
                />
              </>
            )}
          </QueryView>
        </TabsContent>
      </Tabs>
    </div>
  )
}
