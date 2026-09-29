import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config.ts'

export default defineConfig((env) =>
  mergeConfig(viteConfig(env), {
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      css: false,
      restoreMocks: true,
      server: {
        deps: {
          // The wallet kit pulls in CommonJS-only wallet SDKs (@stellar/freighter-api). A browser build
          // pre-bundles them into ESM; under Vitest they would be loaded natively by Node, which cannot see a
          // CommonJS module's named exports. Inlining them puts them through the same transform the app gets.
          inline: [/@creit\.tech[\\/]stellar-wallets-kit/, /@stellar[\\/]freighter-api/],
        },
      },
    },
  }),
)
