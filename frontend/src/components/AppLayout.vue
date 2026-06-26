<template>
  <div class="app-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <router-link to="/" class="logo-link">
          <span class="logo-icon">🐧</span>
          <span v-show="!sidebarCollapsed" class="logo-text">Linux内核补丁匹配系统</span>
        </router-link>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="sidebarCollapsed"
        :router="true"
        class="sidebar-menu"
        background-color="transparent"
        text-color="#546e7a"
        active-text-color="#1976D2"
      >
        <el-menu-item index="/">
          <el-icon><Odometer /></el-icon>
          <span>系统仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/analyze">
          <el-icon><Search /></el-icon>
          <span>宕机日志分析</span>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Collection /></el-icon>
          <span>补丁知识库</span>
        </el-menu-item>
        <el-menu-item index="/history">
          <el-icon><Clock /></el-icon>
          <span>分析历史</span>
        </el-menu-item>
      </el-menu>

      <!-- 用户使用提示 -->
      <div v-show="!sidebarCollapsed" class="sidebar-tips">
        <div class="tips-header">
          <el-icon size="14"><Lightbulb /></el-icon>
          <span>使用提示</span>
        </div>
        <ul class="tips-list">
          <li>上传 dmesg 或 vmcore 文件进行分析</li>
          <li>系统会自动提取故障特征</li>
          <li>支持 LLM 智能分析解释</li>
          <li>在知识库中搜索相关补丁</li>
        </ul>
      </div>

      <!-- API Key 配置入口 -->
      <div v-show="!sidebarCollapsed" class="sidebar-key-status" @click="showKeyDialog = true">
        <div class="key-status-header">
          <el-icon size="14"><Key /></el-icon>
          <span>API Key 设置</span>
        </div>
        <div class="key-status-text">
          <span class="status-dot" :class="apiKeyConfigured ? 'online' : 'offline'"></span>
          <span class="text-sm text-muted">{{ apiKeyConfigured ? '已配置' : '未配置 — 点击设置' }}</span>
        </div>
      </div>

      <!-- 底部状态 -->
      <div class="sidebar-footer" v-show="!sidebarCollapsed">
        <div class="server-status">
          <span class="status-dot" :class="serverOnline ? 'online' : 'offline'"></span>
          <span class="text-sm text-muted">{{ serverOnline ? '服务运行中' : '服务离线' }}</span>
        </div>
        <div class="sidebar-version text-sm text-muted">v1.0.0</div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="main-content">
      <!-- 顶部栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <el-button
            text
            @click="sidebarCollapsed = !sidebarCollapsed"
            class="collapse-btn"
          >
            <el-icon :size="20">
              <Fold v-if="!sidebarCollapsed" />
              <Expand v-else />
            </el-icon>
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="currentTitle">{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="topbar-right">
          <el-tooltip content="API 文档 (Swagger)" placement="bottom">
            <el-button text @click="openApiDocs">
              <el-icon><Document /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip :content="serverOnline ? '服务正常' : '服务离线'" placement="bottom">
            <el-button text @click="checkServerStatus">
              <el-icon><Connection /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </header>

      <!-- 页面内容 -->
      <div class="page-content">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>

    <!-- API Key 配置弹窗 -->
    <el-dialog
      v-model="showKeyDialog"
      title="API Key 配置"
      width="420px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <p class="text-muted mb-4" style="font-size: 13px;">
        输入管理员提供的 <strong>AUTH_API_KEY</strong>，用于访问分析接口。<br/>
        未配置时分析请求将被服务器拒绝（401）。
      </p>
      <el-input
        v-model="keyInput"
        type="password"
        show-password
        placeholder="请输入 AUTH_API_KEY"
        clearable
        @keyup.enter="saveApiKey"
      />
      <template #footer>
        <el-button @click="showKeyDialog = false">取消</el-button>
        <el-button type="primary" @click="saveApiKey" :disabled="!keyInput.trim()">
          保存
        </el-button>
        <el-button v-if="apiKeyConfigured" type="danger" text @click="clearApiKey">
          清除
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { statsApi } from '@/api/stats'

const route = useRoute()
const sidebarCollapsed = ref(false)
const serverOnline = ref(false)
const showKeyDialog = ref(false)
const keyInput = ref('')
const apiKeyConfigured = ref(false)

const activeMenu = computed(() => {
  const path = route.path
  if (path.startsWith('/analyze')) return '/analyze'
  if (path.startsWith('/knowledge')) return '/knowledge'
  if (path.startsWith('/history')) return '/history'
  return '/'
})

const currentTitle = computed(() => route.meta.title || '')

let healthTimer = null

async function checkServerStatus() {
  try {
    const health = await statsApi.health()
    serverOnline.value = health.status === 'healthy'
  } catch {
    serverOnline.value = false
  }
}

function openApiDocs() {
  const apiBase = import.meta.env.VITE_API_BASE || ''
  window.open(`${apiBase.replace('/v1', '')}/docs`, '_blank', 'noopener,noreferrer')
}

function checkApiKey() {
  const stored = localStorage.getItem('api_key')
  apiKeyConfigured.value = !!stored
  if (stored) keyInput.value = stored
}

function saveApiKey() {
  const val = keyInput.value.trim()
  if (!val) return
  localStorage.setItem('api_key', val)
  apiKeyConfigured.value = true
  showKeyDialog.value = false
}

function clearApiKey() {
  localStorage.removeItem('api_key')
  keyInput.value = ''
  apiKeyConfigured.value = false
  showKeyDialog.value = false
}

onMounted(() => {
  checkServerStatus()
  checkApiKey()
  healthTimer = setInterval(checkServerStatus, 30000) // 每 30s 检查
})

onBeforeUnmount(() => {
  if (healthTimer) clearInterval(healthTimer)
})
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ── 侧边栏 ──────────────────────────────────── */
.sidebar {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  background-color: var(--color-bg-sidebar);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  transition: width 0.3s ease, min-width 0.3s ease;
  overflow: hidden;
  z-index: 100;
}
.sidebar.collapsed {
  width: 64px;
  min-width: 64px;
}

.sidebar-header {
  padding: 20px 16px;
  border-bottom: 1px solid var(--color-border);
}
.logo-link {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}
.logo-icon {
  font-size: 28px;
  flex-shrink: 0;
}
.logo-text {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-primary);
  white-space: nowrap;
}

.sidebar-menu {
  flex: 1;
  border-right: none !important;
  padding-top: 8px;
}
.sidebar-menu .el-menu-item {
  margin: 4px 8px;
  border-radius: 8px;
}
.sidebar-menu .el-menu-item.is-active {
  background-color: rgba(25, 118, 210, 0.12) !important;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid var(--color-border);
}
.server-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot.online { background-color: var(--color-success); }
.status-dot.offline { background-color: var(--color-danger); }

/* ── 用户使用提示 ────────────────────────────── */
.sidebar-tips {
  padding: 12px 16px;
  margin: 0 8px;
  background: rgba(25, 118, 210, 0.06);
  border-radius: 8px;
  border: 1px solid rgba(25, 118, 210, 0.12);
}
.tips-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-dark);
  margin-bottom: 8px;
}
.tips-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.tips-list li {
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 1.6;
  padding-left: 12px;
  position: relative;
}
.tips-list li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--color-primary);
  font-size: 10px;
}

/* ── API Key 状态 ────────────────────────────── */
.sidebar-key-status {
  padding: 12px 16px;
  margin: 8px 8px 0 8px;
  background: rgba(255, 193, 7, 0.06);
  border-radius: 8px;
  border: 1px solid rgba(255, 193, 7, 0.15);
  cursor: pointer;
  transition: background 0.2s;
}
.sidebar-key-status:hover {
  background: rgba(255, 193, 7, 0.12);
}
.key-status-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #ffc107;
  margin-bottom: 6px;
}
.key-status-text {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ── 主内容 ──────────────────────────────────── */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── 顶部栏 ──────────────────────────────────── */
.topbar {
  height: 56px;
  min-height: 56px;
  background-color: var(--color-bg-sidebar);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.collapse-btn {
  color: var(--color-text-muted);
}
.topbar-right {
  display: flex;
  gap: 4px;
}

/* ── 页面内容 ────────────────────────────────── */
.page-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  background: #ffffff;
}

/* ── 路由过渡动画 ────────────────────────────── */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateX(10px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(-10px);
}
</style>
