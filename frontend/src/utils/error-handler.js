import { ElNotification } from 'element-plus'

/**
 * 全局错误处理器
 */

export function setupErrorHandler(app) {
  // Vue 错误
  app.config.errorHandler = (err, instance, info) => {
    console.error('[Vue Error]', err, info)
    ElNotification({
      title: '应用错误',
      message: err.message || '发生了意外错误',
      type: 'error',
      duration: 5000,
    })
  }

  // Promise 未捕获异常
  window.addEventListener('unhandledrejection', (event) => {
    console.error('[Unhandled Promise]', event.reason)
    event.preventDefault()
  })
}
