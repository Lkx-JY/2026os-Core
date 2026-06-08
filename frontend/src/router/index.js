import { createRouter, createWebHistory } from 'vue-router'

/**
 * 路由配置
 *
 * 路由结构:
 *   /              → Dashboard    系统概览仪表盘
 *   /analyze       → CrashAnalysis 宕机日志分析 (核心页面)
 *   /knowledge     → KnowledgeBase 补丁知识库搜索
 *   /llm-explain   → LlmExplain   LLM分析解释
 *   /history       → History       历史分析记录
 */
const routes = [
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '系统仪表盘', icon: 'Odometer' },
      },
      {
        path: 'analyze',
        name: 'CrashAnalysis',
        component: () => import('@/views/CrashAnalysis.vue'),
        meta: { title: '宕机日志分析', icon: 'Search' },
      },
      {
        path: 'analyze/:taskId',
        name: 'AnalysisResult',
        component: () => import('@/views/CrashAnalysis.vue'),
        meta: { title: '分析结果', hidden: true },
      },
      {
        path: 'llm-explain',
        name: 'LlmExplain',
        component: () => import('@/views/LlmExplain.vue'),
        meta: { title: 'LLM分析解释', icon: 'MessageSquare' },
      },
      {
        path: 'knowledge',
        name: 'KnowledgeBase',
        component: () => import('@/views/KnowledgeBase.vue'),
        meta: { title: '补丁知识库', icon: 'Collection' },
      },
      {
        path: 'history',
        name: 'History',
        component: () => import('@/views/History.vue'),
        meta: { title: '历史记录', icon: 'Clock' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
    meta: { title: '页面未找到', hidden: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})

// ── 全局前置守卫 — 设置页面标题 ──────────────────
router.beforeEach((to, from, next) => {
  const title = to.meta.title || 'Linux内核补丁匹配系统'
  document.title = `${title} — Linux内核补丁匹配系统`
  next()
})

export default router
