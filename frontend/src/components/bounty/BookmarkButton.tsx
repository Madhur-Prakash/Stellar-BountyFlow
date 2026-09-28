import { Bookmark, BookmarkCheck, LoaderCircle } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { errorMessage } from '@/lib/api/client'
import { useMe } from '@/lib/api/queries/auth'
import { useToggleBookmark } from '@/lib/api/queries/bounties'
import { loginPath } from '@/lib/auth-redirect'
import { cn } from '@/lib/utils'

/** Save / unsave a bounty. Anonymous visitors are sent to login with a return URL. */
export function BookmarkButton({
  bountyId,
  bookmarked,
  variant = 'icon',
  className,
}: {
  bountyId: string
  bookmarked: boolean
  variant?: 'icon' | 'full'
  className?: string
}) {
  const { data: me } = useMe()
  const toggle = useToggleBookmark()
  const navigate = useNavigate()
  const location = useLocation()
  const label = bookmarked ? 'Remove from saved' : 'Save bounty'

  const onClick = () => {
    if (!me) {
      navigate(loginPath(`${location.pathname}${location.search}`))
      return
    }
    toggle.mutate(
      { bountyId, bookmarked },
      {
        onSuccess: () => toast.success(bookmarked ? 'Removed from saved bounties' : 'Saved to your list'),
        onError: (e) => toast.error(errorMessage(e)),
      },
    )
  }

  const Icon = toggle.isPending ? LoaderCircle : bookmarked ? BookmarkCheck : Bookmark

  if (variant === 'full') {
    return (
      <Button
        variant="outline"
        onClick={onClick}
        disabled={toggle.isPending}
        aria-pressed={bookmarked}
        className={className}
      >
        <Icon className={cn(toggle.isPending && 'animate-spin', bookmarked && 'text-primary-emphasis')} />
        {bookmarked ? 'Saved' : 'Save'}
      </Button>
    )
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClick}
          disabled={toggle.isPending}
          aria-pressed={bookmarked}
          aria-label={label}
          className={cn('relative z-10 text-muted-foreground hover:text-foreground', className)}
        >
          <Icon className={cn(toggle.isPending && 'animate-spin', bookmarked && 'text-primary-emphasis')} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{me ? label : 'Sign in to save bounties'}</TooltipContent>
    </Tooltip>
  )
}
