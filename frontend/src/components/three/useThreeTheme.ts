import { useEffect, useState } from 'react'

export type ThreeTheme = { primary: string; dots: string; background: string; dark: boolean }

function read(): ThreeTheme {
  const css = getComputedStyle(document.documentElement)
  const value = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    primary: value('--primary', '#3563e9'),
    dots: value('--muted-foreground', '#6b6b75'),
    background: value('--background', '#fafafa'),
    dark: document.documentElement.classList.contains('dark'),
  }
}

/** The theme colours a WebGL scene needs, kept in sync when the light/dark class on <html> changes. */
export function useThreeTheme(): ThreeTheme {
  const [theme, setTheme] = useState(read)
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])
  return theme
}

/** Whether the browser can draw WebGL at all (false in tests and on some locked-down machines). */
export function webglAvailable(): boolean {
  if (typeof window === 'undefined' || typeof window.WebGLRenderingContext === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}
