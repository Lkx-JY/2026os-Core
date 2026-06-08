import { defineStore } from 'pinia'
import { ref } from 'vue'
import { statsApi } from '@/api/stats'

/**
 * 系统统计 Store — Dashboard 数据
 */

export const useStatsStore = defineStore('stats', () => {
  // ── State ─────────────────────────────────────
  const stats = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const lastUpdated = ref(null)

  // ── Actions ───────────────────────────────────
  async function fetchStats() {
    loading.value = true
    error.value = null
    try {
      stats.value = await statsApi.get()
      lastUpdated.value = new Date()
    } catch (err) {
      error.value = err.message || '获取统计数据失败'
    } finally {
      loading.value = false
    }
  }

  async function checkHealth() {
    try {
      return await statsApi.health()
    } catch {
      return { status: 'unhealthy' }
    }
  }

  return {
    stats,
    loading,
    error,
    lastUpdated,
    fetchStats,
    checkHealth,
  }
})
