import { useSyncExternalStore } from 'react'

export type Countdown = {
  /** Milliseconds remaining (0 once passed). */
  remainingMs: number
  isPast: boolean
  days: number
  hours: number
  minutes: number
  seconds: number
}

// One shared ticker for every countdown on the page.
const listeners = new Set<() => void>()
let timer: number | null = null
let now = Date.now()

function subscribe(cb: () => void) {
  listeners.add(cb)
  if (timer === null && typeof window !== 'undefined') {
    timer = window.setInterval(() => {
      now = Date.now()
      listeners.forEach((l) => l())
    }, 1000)
  }
  return () => {
    listeners.delete(cb)
    if (listeners.size === 0 && timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }
}

const getNow = () => now

export function computeCountdown(target: number | null, current: number): Countdown | null {
  if (target === null || Number.isNaN(target)) return null
  const remainingMs = Math.max(0, target - current)
  const totalSeconds = Math.floor(remainingMs / 1000)
  return {
    remainingMs,
    isPast: remainingMs === 0,
    days: Math.floor(totalSeconds / 86_400),
    hours: Math.floor((totalSeconds % 86_400) / 3600),
    minutes: Math.floor((totalSeconds % 3600) / 60),
    seconds: totalSeconds % 60,
  }
}

/** Live countdown to an ISO timestamp; null when no deadline. */
export function useCountdown(iso: string | null | undefined): Countdown | null {
  const current = useSyncExternalStore(subscribe, getNow, getNow)
  const target = iso ? new Date(iso).getTime() : null
  return computeCountdown(target, current)
}
