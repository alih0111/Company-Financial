import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: 'localhost',
    port: 3000
  },
  build: {
    rollupOptions: {
      output: {
        // جداکردن کتابخانه‌های سنگین برای کش بهتر و لود اولیه سریع‌تر
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts', 'lightweight-charts'],
        },
      },
    },
  },
})
