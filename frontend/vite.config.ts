import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

  // The E2E test wallet provider must never ship: refuse to build production bundles with it enabled.
  if (mode === 'production' && env.VITE_ENABLE_TEST_WALLET) {
    throw new Error(
      'VITE_ENABLE_TEST_WALLET is set for a production build. It enables the E2E-only test wallet provider ' +
        'and must never be set outside end-to-end test runs.',
    )
  }

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      watch: {
        // Test artifacts (Playwright traces/screenshots, coverage) must not trigger HMR full reloads:
        // Playwright writes them while tests run, which would reload every page under test.
        ignored: ['**/test-results*/**', '**/playwright-report/**', '**/blob-report/**', '**/e2e/screenshots/**', '**/coverage/**'],
      },
      proxy: {
        '/api': { target: proxyTarget, changeOrigin: true },
        '/health': { target: proxyTarget, changeOrigin: true },
      },
    },
    preview: {
      port: 4173,
    },
    build: {
      target: 'es2022',
      sourcemap: false,
      chunkSizeWarningLimit: 700,
    },
  }
})
