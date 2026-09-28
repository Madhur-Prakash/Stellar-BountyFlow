/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Versioned REST API base as seen by the browser (default "/api/v1"). */
  readonly VITE_API_BASE_URL?: string
  /** Optional public source repository link shown in the footer / about page. */
  readonly VITE_GITHUB_URL?: string
  /**
   * E2E only: "true" enables the injected test wallet provider (see
   * src/lib/stellar/wallet.ts). vite.config.ts refuses production builds with it.
   */
  readonly VITE_ENABLE_TEST_WALLET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
