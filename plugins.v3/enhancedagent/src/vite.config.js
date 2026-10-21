import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

// Vue 联邦构建配置（宿主约定见 create-moviepilot-plugin SKILL.md）：
// - esm + top-level await（build.target=esnext）
// - 共享 vue/vuetify 由宿主提供（singleton）
// - 产物统一落在 dist/assets/，与 get_render_mode() 返回值一致
export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'EnhancedAgent',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
        './Dashboard': './src/components/Dashboard.vue',
        './AppPage': './src/components/AppPage.vue',
      },
      shared: {
        vue: { requiredVersion: false, generate: false },
        vuetify: { requiredVersion: false, generate: false, singleton: true },
        'vuetify/styles': { requiredVersion: false, generate: false, singleton: true },
      },
      format: 'esm',
    }),
  ],
  build: {
    target: 'esnext',
    cssCodeSplit: true,
    // 产物落到插件根目录 dist/，与 get_render_mode() 的 ("vue", "dist/assets") 一致
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      input: 'src/index.js',
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name][extname]',
      },
    },
  },
})
