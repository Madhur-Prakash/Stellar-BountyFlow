import { MessageCircleQuestion, Send } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { toast } from 'sonner'

import { PaginationBar } from '@/components/layout/PaginationBar'
import { QueryView } from '@/components/layout/QueryView'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorMessage } from '@/lib/api/client'
import { useMe } from '@/lib/api/queries/auth'
import { useAskQuestion, useQuestions } from '@/lib/api/queries/qa'
import { QUESTION_MIN, type QASort } from '@/lib/api/types'
import { loginPath } from '@/lib/auth-redirect'
import { scrollToAnchorWhenReady } from '@/lib/scroll'

import { PostComposer } from './PostComposer'
import { QuestionThread } from './QuestionThread'

const PAGE_SIZE = 10

const SORT_LABELS: Record<QASort, string> = {
  newest: 'Newest',
  helpful: 'Most helpful',
}

/**
 * Public questions and answers on a bounty. Anyone can read; signed-in users ask and reply one level deep.
 * The requester's posts are marked, and the requester accepts one answer per question and pins up to three
 * questions. Notification links land on `#q-<id>`.
 */
export function QuestionsSection({
  bountyRef,
  bountyId,
  className,
}: {
  bountyRef: string
  bountyId: string
  className?: string
}) {
  const { data: me } = useMe()
  const location = useLocation()
  const [sort, setSort] = useState<QASort>('newest')
  const [page, setPage] = useState(1)
  const query = useQuestions(bountyRef, { sort, page, page_size: PAGE_SIZE })
  const ask = useAskQuestion(bountyId)
  const [asking, setAsking] = useState(false)

  // Arriving at "#q-<id>" from a notification: scroll once the thread has rendered.
  useEffect(() => {
    if (!location.hash.startsWith('#q-')) return
    return scrollToAnchorWhenReady(location.hash)
  }, [location.key, location.hash])

  const data = query.data
  const viewer = {
    signedIn: !!me,
    isRequester: !!data?.viewer_is_requester,
    isModerator: !!data?.viewer_is_moderator,
    canPost: !!data?.can_ask,
  }

  return (
    <section aria-labelledby="questions-h" className={className}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="questions-h" className="label-mono">
          Questions{data ? ` (${data.questions_count})` : ''}
        </h2>
        {(data?.total ?? 0) > 1 && (
          <Select value={sort} onValueChange={(v) => setSort(v as QASort)}>
            <SelectTrigger size="sm" className="w-40" aria-label="Sort questions">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(SORT_LABELS) as QASort[]).map((s) => (
                <SelectItem key={s} value={s}>
                  {SORT_LABELS[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <div className="mb-4 rounded-xl border bg-card p-4 shadow-soft sm:p-5">
        {viewer.canPost ? (
          asking ? (
            <PostComposer
              label="Your question"
              submitLabel="Post question"
              submitIcon={<Send />}
              minLength={QUESTION_MIN}
              rows={4}
              autoFocus
              placeholder="Ask about the scope, the acceptance criteria or how the reward is split."
              pending={ask.isPending}
              onCancel={() => setAsking(false)}
              onSubmit={async (body) => {
                await ask.mutateAsync(body, {
                  onSuccess: () => {
                    setAsking(false)
                    setPage(1)
                    setSort('newest')
                    toast.success('Question posted')
                  },
                  onError: (e) => toast.error(errorMessage(e)),
                })
              }}
            />
          ) : (
            <Button variant="outline" onClick={() => setAsking(true)}>
              <MessageCircleQuestion /> Ask a question
            </Button>
          )
        ) : me ? (
          <p className="text-sm text-muted-foreground">
            {data?.closed_reason ?? 'Questions are closed on this bounty.'}
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-muted-foreground">Sign in to ask a question.</p>
            <Button asChild variant="outline" size="sm">
              <Link to={loginPath(`${location.pathname}${location.search}`)}>Sign in</Link>
            </Button>
          </div>
        )}
      </div>

      <QueryView
        query={query}
        skeleton="bounty-questions"
        errorTitle="Questions unavailable"
        isEmpty={(d) => d.items.length === 0}
        empty={{
          icon: MessageCircleQuestion,
          title: 'No questions yet',
          description: 'Answers from the requester appear here for everyone.',
        }}
      >
        {(page_) => (
          <>
            <ul className="space-y-3">
              {page_.items.map((thread) => (
                <QuestionThread key={thread.id} thread={thread} viewer={viewer} />
              ))}
            </ul>
            <PaginationBar
              page={page_.page}
              pages={page_.pages}
              total={page_.total}
              pageSize={page_.page_size}
              onPageChange={setPage}
              itemLabel="questions"
            />
          </>
        )}
      </QueryView>
    </section>
  )
}