import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端开发端口（FastAPI 默认 8000，本地冒烟可用 RG_API_TARGET 覆盖）
const API_TARGET = process.env.RG_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  // 开发期 base='/'（dev server 根路径）；构建期 '/new/' 与后端挂载点一致，
  // 资产固定为 /new/assets/…，避免相对路径在 /new 与 /new/ 间解析漂移。
  base: command === 'build' ? '/new/' : '/',
  server: {
    port: 5173,
    host: true,
    proxy: {
      // 前端只写同源 /api。开发期由本 dev server 代理到后端；
      // 生产期由后端在同一端口托管 webapp，无需代理。
      '/api': { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    // 产物直接输出到后端 demo/webapp/，由 FastAPI 同源托管（hash 路由无需服务端重写）。
    outDir: '../demo/webapp',
    emptyOutDir: true,
    sourcemap: false,
  },
}))
