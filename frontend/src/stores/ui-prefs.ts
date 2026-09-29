import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { safeJSONStorage } from './safe-storage'

export type Theme = 'dark' | 'light'

type UiPrefsState = {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  /** Marketplace layout preference. */
  marketplaceView: 'grid' | 'list'
  setMarketplaceView: (v: 'grid' | 'list') => void
  /**
   * Where this viewer dragged the feedback button, as fractions of the free space (0 = left/top edge,
   * 1 = right/bottom). Fractions rather than pixels so the button keeps its place on a different
   * window size or screen. `null` means it has never been moved and sits in its default corner.
   */
  feedbackPos: { x: number; y: number } | null
  setFeedbackPos: (p: { x: number; y: number }) => void
  resetFeedbackPos: () => void
}

/** Storage key shared with public/theme-init.js (applies the theme before first paint). */
export const UI_PREFS_STORAGE_KEY = 'bf-ui-prefs'

export function applyTheme(theme: Theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.remove('light')
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

export const useUiPrefs = create<UiPrefsState>()(
  persist(
    (set, get) => ({
      theme: 'light',
      setTheme: (theme) => {
        applyTheme(theme)
        set({ theme })
      },
      toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
      marketplaceView: 'grid',
      setMarketplaceView: (marketplaceView) => set({ marketplaceView }),
      feedbackPos: null,
      setFeedbackPos: (feedbackPos) => set({ feedbackPos }),
      resetFeedbackPos: () => set({ feedbackPos: null }),
    }),
    {
      name: UI_PREFS_STORAGE_KEY,
      storage: safeJSONStorage,
      partialize: (s) => ({
        theme: s.theme,
        marketplaceView: s.marketplaceView,
        feedbackPos: s.feedbackPos,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state.theme)
      },
    },
  ),
)
