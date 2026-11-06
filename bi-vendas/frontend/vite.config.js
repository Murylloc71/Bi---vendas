import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Em desenvolvimento, /api é encaminhado para o backend (porta 8000).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', chunkSizeWarningLimit: 1200 },
})
