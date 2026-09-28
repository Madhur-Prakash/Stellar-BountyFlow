import { create } from 'zustand'

/**
 * Client-only auth UI state. The authenticated user itself is server state
 * and lives in the TanStack Query cache (`qk.auth.me`).
 */
type AuthUiState = {
  /** Set when a refresh failed mid-session so the login page can explain why. */
  sessionExpired: boolean
  markSessionExpired: () => void
  clearSessionExpired: () => void
  /**
   * True between choosing "Sign out" and landing on the home page, so route
   * guards send the user home instead of to /login?next=….
   */
  signingOut: boolean
  setSigningOut: (value: boolean) => void
  /** Pre-fills the login form after registration / password reset. */
  lastEmail: string | null
  setLastEmail: (email: string | null) => void
}

export const useAuthUi = create<AuthUiState>()((set) => ({
  sessionExpired: false,
  markSessionExpired: () => set({ sessionExpired: true }),
  clearSessionExpired: () => set({ sessionExpired: false }),
  signingOut: false,
  setSigningOut: (signingOut) => set({ signingOut }),
  lastEmail: null,
  setLastEmail: (lastEmail) => set({ lastEmail }),
}))
