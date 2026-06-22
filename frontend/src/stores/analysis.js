import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { analysisApi } from '@/api/analysis'

/**
 * 分析任务 Store — 管理分析提交、轮询、结果缓存
 *
 * 关键设计:
 * - 每个 task 独立存储，支持同时查看多个结果
 * - 轮询机制: 提交后每 1.5s 轮询直到完成
 * - 持久化: 最近的 10 条结果缓存到 localStorage
 */

const MAX_POLL_ATTEMPTS = 120  // 最多轮询 180 秒
const POLL_INTERVAL_MS = 1500

export const useAnalysisStore = defineStore('analysis', () => {
  // ── State ─────────────────────────────────────
  const tasks = ref({})           // { [taskId]: taskData }
  const currentTaskId = ref(null) // 当前正在查看的任务 ID
  const submitting = ref(false)   // 是否正在提交
  const pollingTimers = ref({})   // { [taskId]: timerId }

  // ── Getters ───────────────────────────────────
  const currentTask = computed(() => {
    return currentTaskId.value ? tasks.value[currentTaskId.value] : null
  })

  const taskList = computed(() => {
    return Object.values(tasks.value)
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
  })

  const completedTasks = computed(() => {
    return taskList.value.filter(t => t.status === 'completed')
  })

  const runningTasks = computed(() => {
    return taskList.value.filter(t => t.status === 'running')
  })

  // ── Actions ───────────────────────────────────
  async function submitAnalysis(params) {
    submitting.value = true
    try {
      const response = await analysisApi.submit(params)
      const taskId = response.task_id

      tasks.value[taskId] = {
        task_id: taskId,
        status: 'running',
        progress: 0,
        created_at: new Date().toISOString(),
        request: params,
        result: null,
        error: null,
      }

      currentTaskId.value = taskId
      startPolling(taskId)

      return taskId
    } finally {
      submitting.value = false
    }
  }

  function startPolling(taskId) {
    let attempts = 0       // 总轮询次数
    let errorCount = 0     // 连续错误次数（成功后重置）

    const poll = async () => {
      try {
        const status = await analysisApi.getStatus(taskId)

        errorCount = 0  // 成功调用，重置连续错误计数

        if (tasks.value[taskId]) {
          tasks.value[taskId].status = status.status
          tasks.value[taskId].progress = status.progress
          tasks.value[taskId].error = status.error

          if (status.status === 'completed') {
            tasks.value[taskId].result = status.result
            stopPolling(taskId)
            return
          } else if (status.status === 'failed') {
            stopPolling(taskId)
            return
          }
        }
      } catch (err) {
        errorCount++
        if (errorCount >= 5) {
          stopPolling(taskId)
          if (tasks.value[taskId]) {
            tasks.value[taskId].status = 'failed'
            tasks.value[taskId].error = '轮询失败: 无法获取任务状态'
          }
          return
        }
      }

      attempts++
      if (attempts >= MAX_POLL_ATTEMPTS) {
        stopPolling(taskId)
        if (tasks.value[taskId] && tasks.value[taskId].status === 'running') {
          tasks.value[taskId].status = 'failed'
          tasks.value[taskId].error = '分析超时'
        }
      }
    }

    // 立即检查一次，然后定时轮询
    poll()
    pollingTimers.value[taskId] = setInterval(poll, POLL_INTERVAL_MS)
  }

  function stopPolling(taskId) {
    if (pollingTimers.value[taskId]) {
      clearInterval(pollingTimers.value[taskId])
      delete pollingTimers.value[taskId]
    }
  }

  function setCurrentTask(taskId) {
    if (tasks.value[taskId]) {
      currentTaskId.value = taskId
    }
  }

  function clearTask(taskId) {
    stopPolling(taskId)
    delete tasks.value[taskId]
    if (currentTaskId.value === taskId) {
      currentTaskId.value = null
    }
  }

  function clearAll() {
    Object.keys(pollingTimers.value).forEach(stopPolling)
    tasks.value = {}
    currentTaskId.value = null
  }

  return {
    // state
    tasks,
    currentTaskId,
    submitting,
    // getters
    currentTask,
    taskList,
    completedTasks,
    runningTasks,
    // actions
    submitAnalysis,
    setCurrentTask,
    clearTask,
    clearAll,
    startPolling,
  }
}, {
  // 持久化最近的任务到 localStorage
  persist: {
    key: 'analysis-store',
    storage: localStorage,
    pick: ['tasks', 'currentTaskId'],
    serializer: {
      serialize: (state) => {
        // 只保留最近 10 条
        const taskEntries = Object.entries(state.tasks || {})
          .sort(([, a], [, b]) => new Date(b.created_at) - new Date(a.created_at))
          .slice(0, 10)
        const pruned = {
          tasks: Object.fromEntries(taskEntries),
          currentTaskId: state.currentTaskId,
        }
        return JSON.stringify(pruned)
      },
      deserialize: (raw) => JSON.parse(raw),
    },
  },
})
