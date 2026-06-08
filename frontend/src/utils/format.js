/**
 * 格式化工具函数
 */

import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

/** 格式化日期时间 */
export function formatDateTime(date) {
  if (!date) return '—'
  return dayjs(date).format('YYYY-MM-DD HH:mm:ss')
}

/** 相对时间 (如 "3分钟前") */
export function formatRelativeTime(date) {
  if (!date) return '—'
  return dayjs(date).fromNow()
}

/** 格式化毫秒为可读时间 */
export function formatDuration(ms) {
  if (!ms && ms !== 0) return '—'
  if (ms < 1000) return `${ms.toFixed(0)} ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(2)} s`
  const minutes = Math.floor(ms / 60000)
  const seconds = ((ms % 60000) / 1000).toFixed(0)
  return `${minutes}m ${seconds}s`
}

/** 格式化大数字 */
export function formatNumber(num) {
  if (!num && num !== 0) return '—'
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`
  return num.toLocaleString()
}

/** 格式化百分比 */
export function formatPercent(value) {
  if (value == null) return '—'
  return `${(value * 100).toFixed(1)}%`
}

/** 截断 commit hash */
export function shortHash(hash, len = 12) {
  if (!hash) return '—'
  return hash.length > len ? hash.substring(0, len) : hash
}

/** 获取 Bug 类型标签颜色 */
export function bugTypeColor(type) {
  const colors = {
    race_condition: 'danger',
    use_after_free: 'warning',
    null_pointer_dereference: 'info',
    memory_corruption: 'danger',
    deadlock: 'warning',
    soft_lockup: '',
  }
  return colors[type] || ''
}

/** 获取 Bug 类型中文名 */
export function bugTypeLabel(type) {
  const labels = {
    race_condition: '竞态条件',
    use_after_free: '释放后使用 (UAF)',
    null_pointer_dereference: '空指针解引用',
    memory_corruption: '内存损坏',
    deadlock: '死锁',
    soft_lockup: '软锁定',
    unknown: '未知',
  }
  return labels[type] || type
}

/** 获取状态标签颜色 */
export function statusColor(status) {
  const colors = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
  }
  return colors[status] || 'info'
}

/** 获取状态中文名 */
export function statusLabel(status) {
  const labels = {
    pending: '等待中',
    running: '分析中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[status] || status
}

/** 拷贝到剪贴板 */
export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 降级方案
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    return true
  }
}
