import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const canvasApiTarget = env.VITE_CANVAS_API_TARGET || 'http://localhost:8003'
  const canvasWsTarget = env.VITE_CANVAS_WS_TARGET || 'ws://localhost:8003'
  const gatewayApiTarget = env.VITE_GATEWAY_API_TARGET || 'http://localhost:18080'

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 3000,
      proxy: {
        '/api/v1': {
          target: gatewayApiTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
        '/api': {
          target: canvasApiTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
        '/ws': {
          target: canvasWsTarget,
          ws: true,
        },
      },
    },
  }
})
