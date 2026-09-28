import { createJSONStorage, type StateStorage } from 'zustand/middleware'

/** localStorage wrapper that never throws (private mode, blocked storage, SSR). */
const safeLocalStorage: StateStorage = {
  getItem: (name) => {
    try {
      return window.localStorage.getItem(name)
    } catch {
      return null
    }
  },
  setItem: (name, value) => {
    try {
      window.localStorage.setItem(name, value)
    } catch {
      /* storage unavailable: preference simply isn't persisted */
    }
  },
  removeItem: (name) => {
    try {
      window.localStorage.removeItem(name)
    } catch {
      /* ignore */
    }
  },
}

export const safeJSONStorage = createJSONStorage(() => safeLocalStorage)
