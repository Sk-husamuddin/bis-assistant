import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/query': 'http://127.0.0.1:8000',
      '/speak': 'http://127.0.0.1:8000',
      '/transcribe': 'http://127.0.0.1:8000',
      '/audio_cache': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
