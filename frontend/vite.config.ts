import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Use same env var as frontend runtime (VITE_API_BASE_URL) so dev-proxy and
  // runtime config can't drift apart. Fallback is identical to lib/api.ts.
  const target = (env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        '/health': target,
        '/query': target,
        '/speak': target,
        '/transcribe': target,
        '/audio_cache': target,
      },
    },
    build: {
      outDir: 'dist',
    },
  }
})
