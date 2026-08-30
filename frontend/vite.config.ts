import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // fileURLToPath, not `.pathname`: on Windows `.pathname` yields
    // "/C:/Users/..." -- a leading slash before the drive letter -- which Vite
    // cannot resolve, so every `@/...` import fails to find its module.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    // The API is proxied rather than called cross-origin, so the browser sees
    // one origin in development and CORS never enters the picture.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
