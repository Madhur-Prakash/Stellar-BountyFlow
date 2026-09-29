import {
  ArrowBigUp,
  Check,
  CornerDownRight,
  EyeOff,
  Flag,
  LoaderCircle,
  Pencil,
  Pin,
  PinOff,
  Reply,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { ReasonDialog } from '@/components/common/ReasonDialog'
import { UserAvatar } from '@/components/common/UserAvatar'
import { SafeMarkdown } from '@/components/markdown/SafeMarkdown'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api/client'
import {
  useAcceptAnswer,
  useDeletePost,
  useEditPost,
  useModeratePost,
  usePinQuestion,
  useReply,
  useReportPost,
  useVote,
} from '@/lib/api/queries/qa'
import { QUESTION_MIN, REPLY_MIN, type QAPost, type QAThread } from '@/lib/api/types'
import { formatDateTime, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

import { PostComposer } from './PostComposer'

type Viewer = { signedIn: boolean; isRequester: boolean; isModerator: boolean; canPost: boolean }

function PostMeta({ post }: { post: QAPost }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">
        {post.author ? post.author.display_name : 'Deleted'}
      </span>
      {post.is_requester && <Badge variant="info">Requester</Badge>}
      {post.is_accepted && (
        <Badge variant="cyan">
          <Check aria-hidden /> Accepted answer
        </Badge>
      )}
      {post.is_pinned && (
        <Badge variant="muted">
          <Pin aria-hidden /> Pinned
        </Badge>
      )}
      {post.is_hidden && (
        <Badge variant="warning">
          <EyeOff aria-hidden /> Hidden
        </Badge>
      )}
      <time dateTime={post.created_at} title={formatDateTime(post.created_at)}>
        {formatRelative(post.created_at)}
      </time>
      {post.edited_at && (
        <span title={`Edited ${formatDateTime(post.edited_at)}`} className="italic">
          edited
        </span>
      )}
    </div>
  )
}

function UpvoteButton({ post, viewer }: { post: QAPost; viewer: Viewer }) {
  const vote = useVote()
  const own = post.is_mine
  const disabled = !viewer.signedIn || own || post.is_deleted || post.is_hidden
  return (
    <Button
      variant="ghost"
      size="sm"
      aria-pressed={post.viewer_voted}
      aria-label={post.viewer_voted ? 'Remove your upvote' : 'Upvote'}
      disabled={disabled || vote.isPending}
      className={cn('gap-1 px-2 text-muted-foreground', post.viewer_voted && 'text-primary-emphasis')}
      onClick={() =>
        vote.mutate(
          { postId: post.id, up: !post.viewer_voted },
          { onError: (e) => toast.error(errorMessage(e)) },
        )
      }
    >
      <ArrowBigUp className={cn(post.viewer_voted && 'fill-current')} aria-hidden />
      <span className="tabular-nums">{post.upvotes}</span>
    </Button>
  )
}

/** The author's own edit and delete, the requester's accept, and reporting / moderation for everyone else. */
function PostActions({
  post,
  viewer,
  onEdit,
  onReply,
}: {
  post: QAPost
  viewer: Viewer
  onEdit: () => void
  onReply?: () => void
}) {
  const remove = useDeletePost()
  const accept = useAcceptAnswer()
  const pin = usePinQuestion()
  const report = useReportPost()
  const moderate = useModeratePost()
  const [dialog, setDialog] = useState<'report' | 'hide' | 'delete' | null>(null)
  const isQuestion = post.parent_id === null
  const onError = (e: unknown) => toast.error(errorMessage(e))

  return (
    <div className="flex flex-wrap items-center gap-0.5">
      {onReply && viewer.canPost && (
        <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={onReply}>
          <Reply /> Reply
        </Button>
      )}
      {viewer.isRequester && !isQuestion && !post.is_deleted && !post.is_hidden && (
        <Button
          variant="ghost"
          size="sm"
          className={cn('text-muted-foreground', post.is_accepted && 'text-primary-emphasis')}
          disabled={accept.isPending}
          onClick={() =>
            accept.mutate(
              { postId: post.id, accepted: !post.is_accepted },
              {
                onSuccess: () =>
                  toast.success(post.is_accepted ? 'Answer unaccepted' : 'Answer accepted'),
                onError,
              },
            )
          }
        >
          {accept.isPending ? <LoaderCircle className="animate-spin" /> : <Check />}
          {post.is_accepted ? 'Unaccept' : 'Accept'}
        </Button>
      )}
      {viewer.isRequester && isQuestion && !post.is_deleted && !post.is_hidden && (
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          disabled={pin.isPending}
          onClick={() =>
            pin.mutate(
              { postId: post.id, pinned: !post.is_pinned },
              { onSuccess: () => toast.success(post.is_pinned ? 'Unpinned' : 'Pinned'), onError },
            )
          }
        >
          {post.is_pinned ? <PinOff /> : <Pin />}
          {post.is_pinned ? 'Unpin' : 'Pin'}
        </Button>
      )}
      {post.is_mine && !post.is_deleted && (
        <>
          <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={onEdit}>
            <Pencil /> Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            disabled={remove.isPending}
            onClick={() => setDialog('delete')}
          >
            {remove.isPending ? <LoaderCircle className="animate-spin" /> : <Trash2 />} Delete
          </Button>
        </>
      )}
      {viewer.signedIn && !post.is_mine && !post.is_deleted && (
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          onClick={() => setDialog('report')}
        >
          <Flag /> Report
        </Button>
      )}
      {viewer.isModerator && !post.is_deleted && (
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          disabled={moderate.isPending}
          onClick={() => {
            if (post.is_hidden) {
              moderate.mutate(
                { postId: post.id, body: { action: 'UNHIDE', reason: 'Restored by a moderator' } },
                { onSuccess: () => toast.success('Post visible again'), onError },
              )
            } else {
              setDialog('hide')
            }
          }}
        >
          <EyeOff /> {post.is_hidden ? 'Unhide' : 'Hide'}
        </Button>
      )}

      <ReasonDialog
        open={dialog === 'delete'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={isQuestion ? 'Delete this question?' : 'Delete this reply?'}
        description={
          isQuestion
            ? 'The question is removed. Replies to it stay, so the thread still reads.'
            : 'The reply is removed from the thread.'
        }
        label="Reason"
        required={false}
        confirmLabel="Delete"
        destructive
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutateAsync(post.id, { onSuccess: () => toast.success('Deleted'), onError })
        }
      />
      <ReasonDialog
        open={dialog === 'report'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={isQuestion ? 'Report this question' : 'Report this reply'}
        description="For spam, abuse or anything that does not belong on a bounty. Moderators review every report."
        label="What’s wrong?"
        minLength={10}
        confirmLabel="Send report"
        destructive
        pending={report.isPending}
        onConfirm={(reason) =>
          report.mutateAsync(
            { postId: post.id, reason },
            { onSuccess: () => toast.success('Report sent to the moderators. Thank you.'), onError },
          )
        }
      />
      <ReasonDialog
        open={dialog === 'hide'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Hide this post?"
        description="It stays visible to its author and to moderators, and open reports on it are marked as actioned."
        label="Reason"
        minLength={5}
        confirmLabel="Hide post"
        destructive
        pending={moderate.isPending}
        onConfirm={(reason) =>
          moderate.mutateAsync(
            { postId: post.id, body: { action: 'HIDE', reason } },
            { onSuccess: () => toast.success('Post hidden'), onError },
          )
        }
      />
    </div>
  )
}

function PostBody({ post }: { post: QAPost }) {
  if (post.is_deleted) return <p className="text-sm text-muted-foreground italic">This post was deleted.</p>
  if (post.body === null)
    return <p className="text-sm text-muted-foreground italic">A moderator hid this post.</p>
  return <SafeMarkdown className="text-sm leading-6">{post.body}</SafeMarkdown>
}

function ThreadReply({ post, viewer }: { post: QAPost; viewer: Viewer }) {
  const edit = useEditPost()
  const [editing, setEditing] = useState(false)
  return (
    <li
      className={cn(
        'flex gap-3 border-l-2 py-3 pl-4',
        post.is_accepted ? 'border-primary/40 bg-primary/5' : 'border-border',
      )}
    >
      {post.author ? (
        <UserAvatar user={post.author} className="mt-0.5 size-7" />
      ) : (
        <span className="mt-0.5 size-7 shrink-0 rounded-full border bg-surface" aria-hidden />
      )}
      <div className="min-w-0 flex-1 space-y-1.5">
        <PostMeta post={post} />
        {editing ? (
          <PostComposer
            label="Edit your reply"
            hideLabel
            submitLabel="Save"
            initialValue={post.body ?? ''}
            minLength={REPLY_MIN}
            rows={3}
            pending={edit.isPending}
            autoFocus
            onCancel={() => setEditing(false)}
            onSubmit={async (body) => {
              await edit.mutateAsync(
                { postId: post.id, body },
                { onSuccess: () => setEditing(false), onError: (e) => toast.error(errorMessage(e)) },
              )
            }}
          />
        ) : (
          <>
            <PostBody post={post} />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <UpvoteButton post={post} viewer={viewer} />
              <PostActions post={post} viewer={viewer} onEdit={() => setEditing(true)} />
            </div>
          </>
        )}
      </div>
    </li>
  )
}

/** One question with its replies. Deep links from notifications land on `#q-<id>`. */
export function QuestionThread({ thread, viewer }: { thread: QAThread; viewer: Viewer }) {
  const edit = useEditPost()
  const reply = useReply()
  const [editing, setEditing] = useState(false)
  const [replying, setReplying] = useState(false)

  return (
    <li
      id={`q-${thread.id}`}
      className="scroll-mt-24 rounded-xl border bg-card p-4 shadow-soft sm:p-5"
      aria-labelledby={`q-${thread.id}-author`}
    >
      <div className="flex gap-3">
        {thread.author ? (
          <UserAvatar user={thread.author} className="mt-0.5 size-8" />
        ) : (
          <span className="mt-0.5 size-8 shrink-0 rounded-full border bg-surface" aria-hidden />
        )}
        <div className="min-w-0 flex-1 space-y-2">
          <div id={`q-${thread.id}-author`}>
            <PostMeta post={thread} />
          </div>
          {editing ? (
            <PostComposer
              label="Edit your question"
              hideLabel
              submitLabel="Save"
              initialValue={thread.body ?? ''}
              minLength={QUESTION_MIN}
              rows={4}
              pending={edit.isPending}
              autoFocus
              onCancel={() => setEditing(false)}
              onSubmit={async (body) => {
                await edit.mutateAsync(
                  { postId: thread.id, body },
                  { onSuccess: () => setEditing(false), onError: (e) => toast.error(errorMessage(e)) },
                )
              }}
            />
          ) : (
            <>
              <PostBody post={thread} />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <UpvoteButton post={thread} viewer={viewer} />
                <PostActions
                  post={thread}
                  viewer={viewer}
                  onEdit={() => setEditing(true)}
                  onReply={() => setReplying(true)}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {thread.replies.length > 0 && (
        <ul className="mt-2 space-y-1 pl-3 sm:pl-11">
          {thread.replies.map((r) => (
            <ThreadReply key={r.id} post={r} viewer={viewer} />
          ))}
        </ul>
      )}

      {replying && viewer.canPost && (
        <div className="mt-3 sm:pl-11">
          <PostComposer
            label="Your reply"
            submitLabel="Post reply"
            submitIcon={<CornerDownRight />}
            minLength={REPLY_MIN}
            rows={3}
            pending={reply.isPending}
            autoFocus
            onCancel={() => setReplying(false)}
            onSubmit={async (body) => {
              await reply.mutateAsync(
                { postId: thread.id, body },
                {
                  onSuccess: () => {
                    setReplying(false)
                    toast.success('Reply posted')
                  },
                  onError: (e) => toast.error(errorMessage(e)),
                },
              )
            }}
          />
        </div>
      )}
    </li>
  )
}
