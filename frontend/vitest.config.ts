/**
 * Test config, kept separate from `vite.config.ts`.
 *
 * Vitest re-exports Vite's types, and when the two resolve slightly different
 * Vite versions the plugin types stop being assignable. Splitting the files
 * sidesteps that entirely and keeps the app build config free of test concerns.
 */
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [react()],
  // The app's tsconfig sets jsx: react-jsx; this config has its own esbuild
  // pass, so the automatic runtime has to be stated here too or JSX compiles
  // to `React.createElement` with no React import in scope.
  esbuild: { jsx: 'automatic' },
  resolve: {
    // fileURLToPath, not `.pathname`: on Windows `.pathname` yields
    // "/C:/Users/..." -- a leading slash before the drive letter -- which Vite
    // cannot resolve, so every `@/...` import fails to find its module.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
