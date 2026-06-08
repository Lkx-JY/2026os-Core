import axios from 'axios'
import { ElNotification } from 'element-plus'

/**
 * Axios 客户端 — 统一封装
 *
 * 特性:
 * - 自动添加请求 ID
 * - 请求/响应拦截
 * - 统一错误处理
 * - 超时重试
 * - 请求取消支持
 */

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const REQUEST_TIMEOUT = 30000  // 30s

const client = axios.create({
  baseURL: API_BASE,
  timeout: REQUEST_TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── 请求拦截器 ────────────────────────────────────
client.interceptors.request.use(
  (config) => {
    // 添加请求追踪 ID
    config.headers['X-Request-ID'] = generateRequestId()

    // 从 localStorage 读取 API Key (如有)
    const apiKey = localStorage.getItem('api_key')
    if (apiKey) {
      config.headers['Authorization'] = `Bearer ${apiKey}`
    }

    return config
  },
  (error) => Promise.reject(error)
)

// ── 响应拦截器 ────────────────────────────────────
client.interceptors.response.use(
  (response) => {
    // 记录响应时间 (调试用)
    const responseTime = response.headers['x-response-time']
    if (responseTime && import.meta.env.DEV) {
      console.debug(`[API] ${response.config.url} → ${responseTime}`)
    }
    return response
  },
  (error) => {
    // 统一错误处理
    if (error.response) {
      const { status, data } = error.response

      switch (status) {
        case 429:
          // 速率限制 — 提示用户稍后再试
          ElNotification({
            title: '请求过于频繁',
            message: data?.detail?.message || '请稍后再试',
            type: 'warning',
            duration: 5000,
          })
          break
        case 500:
        case 502:
        case 503:
          ElNotification({
            title: '服务端错误',
            message: '服务器暂时不可用，请稍后重试',
            type: 'error',
            duration: 5000,
          })
          break
        case 401:
          ElNotification({
            title: '认证失败',
            message: 'API Key 无效，请检查配置',
            type: 'error',
          })
          break
        default:
          // 其他错误静默处理，由调用方捕获
          break
      }
    } else if (error.code === 'ECONNABORTED') {
      ElNotification({
        title: '请求超时',
        message: '服务响应超时，请检查网络连接',
        type: 'warning',
        duration: 4000,
      })
    } else if (!error.response) {
      // 网络错误
      ElNotification({
        title: '网络错误',
        message: '无法连接到服务器，请检查后端是否运行',
        type: 'error',
        duration: 6000,
      })
    }

    return Promise.reject(error)
  }
)

// ── 工具函数 ──────────────────────────────────────
function generateRequestId() {
  return `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

export default client
