import { useCallback, useEffect, useRef, useState } from 'react'

/** Returns `value` after it has stopped changing for `delay` ms. */
export function useDebounce<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(t)
  }, [value, delay])
  return debounced
}

/** Returns a stable function that invokes `fn` once calls stop for `delay` ms. */
export function useDebouncedCallback<A extends unknown[]>(fn: (...args: A) => void, delay = 300) {
  const timer = useRef<number | undefined>(undefined)
  const latest = useRef(fn)
  useEffect(() => {
    latest.current = fn
  })
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return useCallback(
    (...args: A) => {
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => latest.current(...args), delay)
    },
    [delay],
  )
}
