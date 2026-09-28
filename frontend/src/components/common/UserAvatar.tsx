import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import type { UserSummary } from '@/lib/api/types'
import { cn } from '@/lib/utils'

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const letters = parts.length >= 2 ? parts[0]![0]! + parts[1]![0]! : (parts[0] ?? '?').slice(0, 2)
  return letters.toUpperCase()
}

export function UserAvatar({
  user,
  className,
}: {
  user: Pick<UserSummary, 'display_name' | 'username' | 'avatar_url'>
  className?: string
}) {
  const name = user.display_name || user.username
  return (
    <Avatar className={cn('size-8 border border-border', className)}>
      {user.avatar_url && <AvatarImage src={user.avatar_url} alt="" />}
      <AvatarFallback className="bg-surface-raised text-[0.7rem] font-medium text-muted-foreground">
        {initials(name)}
      </AvatarFallback>
    </Avatar>
  )
}
