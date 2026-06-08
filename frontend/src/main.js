import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import { setupErrorHandler } from './utils/error-handler'

// 样式
import 'element-plus/dist/index.css'
import 'highlight.js/styles/github-dark.min.css'
import './styles/global.css'

const app = createApp(App)

// ── Pinia 状态管理 ────────────────────────────────
const pinia = createPinia()
pinia.use(piniaPersistedstate)  // 持久化关键状态到 localStorage
app.use(pinia)

// ── Vue Router ───────────────────────────────────
app.use(router)

// ── Element Plus (中文) ──────────────────────────
app.use(ElementPlus, { locale: zhCn })

// ── 注册所有 Element Plus 图标 ───────────────────
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// ── 全局错误处理 ────────────────────────────────
setupErrorHandler(app)

app.mount('#app')
