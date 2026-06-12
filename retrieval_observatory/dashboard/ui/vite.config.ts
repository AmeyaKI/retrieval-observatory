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
      '/dbs': 'http://localhost:4000',
      '/runs': 'http://localhost:4000',
      '/compare': 'http://localhost:4000',
      '/datasets': 'http://localhost:4000',
    },
  },
})
