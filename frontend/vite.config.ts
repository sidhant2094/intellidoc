import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiBase = (env.VITE_API_BASE_URL ?? '').trim()

  if (command === 'build') {
    if (!apiBase && process.env.VERCEL) {
      // On Vercel the frontend and API live on different hosts; a relative /api would 404.
      throw new Error('VITE_API_BASE_URL must be set in the Vercel project (e.g. https://<service>.onrender.com).')
    }
    if (apiBase && !/^https?:\/\/[^/\s]+\/?$/.test(apiBase)) {
      throw new Error(`VITE_API_BASE_URL must be an origin like https://api.example.com, got "${apiBase}".`)
    }
    if (!apiBase) console.warn('VITE_API_BASE_URL is not set: the build will call /api on its own host.')
  }

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      strictPort: true,
      // Local development: the browser calls /api and Vite forwards it to the backend on :8000.
      proxy: {
        '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      },
    },
  }
})
