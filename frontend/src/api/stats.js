import client from './client'

/**
 * 系统统计 API
 */

export const statsApi = {
  /**
   * 获取系统概览统计
   */
  async get() {
    const { data } = await client.get('/stats')
    return data
  },

  /**
   * 健康检查
   */
  async health() {
    const { data } = await client.get('/health', { baseURL: '' })
    return data
  },
}
