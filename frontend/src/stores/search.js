import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { searchApi } from '@/api/search'

/**
 * 搜索 Store — 管理补丁知识库搜索状态
 */

export const useSearchStore = defineStore('search', () => {
  // ── State ─────────────────────────────────────
  const query = ref('')
  const results = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const facets = ref(null)

  // 过滤条件
  const filterSubsystem = ref(null)
  const filterBugType = ref(null)
  const filterVersion = ref('')
  const retrievalMode = ref('fast')  // ★ 检索模式: fast | standard | deep

  // 子系统 / Bug 类型选项 (用于下拉框)
  const subsystemOptions = ref([])
  const bugTypeOptions = ref([])

  // Commit 详情缓存
  const commitCache = ref({})

  // ── Getters ───────────────────────────────────
  const totalPages = computed(() => Math.ceil(total.value / pageSize.value))
  const hasResults = computed(() => results.value.length > 0)

  // ── Actions ───────────────────────────────────
  async function doSearch(searchQuery) {
    if (searchQuery !== undefined) {
      query.value = searchQuery
    }
    if (!query.value.trim()) return

    loading.value = true
    try {
      const data = await searchApi.search({
        query: query.value,
        subsystem: filterSubsystem.value,
        bug_type: filterBugType.value,
        kernel_version: filterVersion.value || undefined,
        page: page.value,
        page_size: pageSize.value,
        retrieval_mode: retrievalMode.value,
      })
      results.value = data.results
      total.value = data.total
      facets.value = data.facets
    } finally {
      loading.value = false
    }
  }

  async function getCommitDetail(commitId) {
    if (commitCache.value[commitId]) return commitCache.value[commitId]
    const data = await searchApi.getDetail(commitId)
    commitCache.value[commitId] = data
    return data
  }

  async function loadFilterOptions() {
    try {
      const [subsystems, bugTypes] = await Promise.all([
        searchApi.listSubsystems(),
        searchApi.listBugTypes(),
      ])
      subsystemOptions.value = subsystems.map(s => ({ label: s, value: s }))
      bugTypeOptions.value = bugTypes.map(b => ({ label: b, value: b }))
    } catch (err) {
      console.warn('加载过滤选项失败，使用默认值:', err.message || err)
      // 提供合理的默认回退值，确保 UI 不会空白
      subsystemOptions.value = [
        { label: 'mm', value: 'mm' },
        { label: 'fs', value: 'fs' },
        { label: 'net', value: 'net' },
        { label: 'kernel', value: 'kernel' },
        { label: 'drivers', value: 'drivers' },
      ]
      bugTypeOptions.value = [
        { label: 'use_after_free', value: 'use_after_free' },
        { label: 'null_pointer_dereference', value: 'null_pointer_dereference' },
        { label: 'race_condition', value: 'race_condition' },
        { label: 'deadlock', value: 'deadlock' },
        { label: 'memory_corruption', value: 'memory_corruption' },
      ]
    }
  }

  function setPage(p) {
    page.value = p
    doSearch()
  }

  function resetFilters() {
    filterSubsystem.value = null
    filterBugType.value = null
    filterVersion.value = ''
  }

  return {
    query, results, total, page, pageSize, loading, facets,
    filterSubsystem, filterBugType, filterVersion, retrievalMode,
    subsystemOptions, bugTypeOptions, commitCache,
    totalPages, hasResults,
    doSearch, getCommitDetail, loadFilterOptions, setPage, resetFilters,
  }
})
