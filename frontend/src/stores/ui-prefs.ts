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
    }),
    {
      name: UI_PREFS_STORAGE_KEY,
      storage: safeJSONStorage,
      partialize: (s) => ({ theme: s.theme, marketplaceView: s.marketplaceView }),
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state.theme)
      },
    },
  ),
)
