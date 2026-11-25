import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

/**
 * Vite 7 构建与开发服务器配置（Electron 35 + 局域网协同 Web 端）
 * - base: './' 确保 Electron 生产模式与相对路径静态托管均可正确解析资源
 * - 按领域切分重型生信可视化依赖，压缩首屏主包体积与加载耗时
 */
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    minify: 'terser',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, '/')
          if (normalized.includes('/src/stores/strain')) return 'store-strain'
          if (normalized.includes('/resources/locales/')) return 'locales-bundle'
          if (!normalized.includes('node_modules')) return undefined
          if (normalized.includes('/vue/') || normalized.includes('/vue-router/') || normalized.includes('/pinia/') || normalized.includes('/@vueuse/')) {
            return 'vendor-vue'
          }
          if (normalized.includes('plotly.js-dist-min')) return 'vendor-plotly'
          if (normalized.includes('/igv/')) return 'vendor-igv'
          if (normalized.includes('/three/')) return 'vendor-three'
          if (normalized.includes('/cgview/')) return 'vendor-cgview'
          if (normalized.includes('/d3') || normalized.includes('/d3-')) return 'vendor-d3'
          if (normalized.includes('/exceljs/')) return 'vendor-exceljs'
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    fs: {
      allow: ['..', '../..'],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
