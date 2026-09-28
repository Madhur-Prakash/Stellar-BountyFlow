import { Bell, CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/PageHeader'
import { PaginationBar } from '@/components/layout/PaginationBar'
import { Button } from '@/components/ui/button'
import { Card, CardFooter } from '@/components/ui/card'
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

import { CardQuery, CardToolbar } from './workspace-ui'

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
    <li
      className={cn(
        'grid gap-x-6 gap-y-1.5 px-4 py-3.5 sm:px-5 md:grid-cols-[minmax(0,1fr)_10rem_7rem]',
        unread && 'bg-primary/[0.035] shadow-[inset_2px_0_0_var(--primary)]',
      )}
    >
      <div className="min-w-0">
        <h3 className={cn('text-sm', unread ? 'font-semibold' : 'font-medium')}>
          {link ? (
            <Link to={link} onClick={onOpen} className="hover:underline">
              {n.title}
            </Link>
          ) : (
            n.title
          )}
          {unread && <span className="sr-only"> (unread)</span>}
        </h3>
        <p className="mt-0.5 text-sm text-muted-foreground">{n.message}</p>
      </div>
      <div className="flex items-center gap-3 text-xs text-muted-foreground md:block md:pt-0.5">
        <span>{humanize(n.notification_type)}</span>
        <time dateTime={n.created_at} title={formatDateTime(n.created_at)} className="tabular-nums md:hidden">
          {formatRelative(n.created_at)}
        </time>
      </div>
      <div className="flex items-start justify-between gap-2 md:flex-col md:items-end md:justify-start">
        <time
          dateTime={n.created_at}
          title={formatDateTime(n.created_at)}
          className="hidden pt-0.5 text-xs text-muted-foreground tabular-nums md:block"
        >
          {formatRelative(n.created_at)}
        </time>
        {unread && (
          <Button
            variant="ghost"
            size="xs"
            className="-ml-2 md:-mr-2 md:ml-0"
            onClick={() => markRead.mutate(n.id, { onError: (e) => toast.error(errorMessage(e)) })}
            disabled={markRead.isPending}
          >
            Mark as read
          </Button>
        )}
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
    <div>
      <PageHeader
        title="Notifications"
        description={
          query.data
            ? `${query.data.unread_count} unread`
            : 'Updates about your bounties, applications and payouts.'
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
      >
        <Card className="gap-0 py-0">
          <CardToolbar>
            <TabsList className="h-9">
              <TabsTrigger value="all" className="px-3">
                All
              </TabsTrigger>
              <TabsTrigger value="unread" className="px-3">
                Unread
              </TabsTrigger>
            </TabsList>
          </CardToolbar>

          <TabsContent value={unreadOnly ? 'unread' : 'all'}>
            <CardQuery
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
                  <ul aria-label="Notifications" className="divide-y">
                    {data.items.map((n) => (
                      <NotificationRow key={n.id} n={n} />
                    ))}
                  </ul>
                  <CardFooter className="px-4 py-3 sm:px-5">
                    <PaginationBar
                      page={data.page}
                      pages={data.pages}
                      total={data.total}
                      pageSize={data.page_size}
                      onPageChange={setPage}
                      itemLabel="notifications"
                      className="w-full pt-0"
                    />
                  </CardFooter>
                </>
              )}
            </CardQuery>
          </TabsContent>
        </Card>
      </Tabs>
    </div>
  )
}
