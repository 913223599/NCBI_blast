import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/**
 * Vite 配置 - 适配 QWebEngineView 环境
 * - base: './' 确保 file:// 协议下资源路径正确
 * - build.outDir: 'dist' 最终由 PyQt 加载
 */
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    minify: 'terser',
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['vue', 'vue-router', 'pinia']
        }
      }
    }
  },
  server: {
    port: 5173
  }
})
