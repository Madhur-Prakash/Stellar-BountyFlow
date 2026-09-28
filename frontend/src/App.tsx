import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { RouterProvider } from 'react-router'

import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { queryClient } from '@/lib/query-client'
import { createAppRouter } from '@/router'

/**
 * Providers: TanStack Query → Tooltips → Router, plus toasts. Theme is a zustand store. Motion is GSAP throughout
 * (lib/gsap.ts); every animation checks motionAllowed(), which honours prefers-reduced-motion.
 */
export default function App() {
  const [router] = useState(createAppRouter)
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
