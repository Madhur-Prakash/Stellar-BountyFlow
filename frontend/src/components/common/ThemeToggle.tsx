import { Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { originOf, switchTheme } from '@/lib/theme-transition'
import { useUiPrefs } from '@/stores/ui-prefs'

export function ThemeToggle({ className }: { className?: string }) {
  const theme = useUiPrefs((s) => s.theme)
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={(e) => switchTheme(next, originOf(e.currentTarget))}
          aria-label={`Switch to ${next} theme`}
          className={className}
        >
          {theme === 'dark' ? <Sun /> : <Moon />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>Switch to {next} theme</TooltipContent>
    </Tooltip>
  )
}
