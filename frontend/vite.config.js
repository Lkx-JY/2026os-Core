import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },

  server: {
    port: 5173,
    host: '0.0.0.0',
    // 代理 API 请求到后端 FastAPI 服务
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // WebSocket 支持 (未来实时通知)
        ws: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },

  build: {
    // 生产构建优化
    target: 'es2021',
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    // 代码分割
    rollupOptions: {
      output: {
        manualChunks: {
          'element-plus': ['element-plus'],
          'echarts': ['echarts', 'vue-echarts'],
          'highlight': ['highlight.js'],
        },
      },
    },
    // 压缩
    minify: 'esbuild',
    chunkSizeWarningLimit: 600,
  },

  // 预加载优化
  optimizeDeps: {
    include: ['element-plus', 'axios', 'echarts', 'highlight.js'],
  },
})
