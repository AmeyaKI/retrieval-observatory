import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/dbs': 'http://localhost:8000',
      '/runs': 'http://localhost:8000',
      '/compare': 'http://localhost:8000',
      '/datasets': 'http://localhost:8000',
    },
  },
})
