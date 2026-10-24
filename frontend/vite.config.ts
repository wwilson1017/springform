import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import springformApps from './vite-plugin-apps'

const BACKEND = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss(), springformApps()],
  server: {
    // `^/up$` is a regex key: a plain '/up' prefix would also proxy '/upload…' and '/updates'.
    proxy: { '/api': BACKEND, '^/up$': BACKEND },
  },
  build: { outDir: 'dist' },
})
