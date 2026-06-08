import client from './client'

/**
 * 宕机日志分析 API
 */

export const analysisApi = {
  /**
   * 提交宕机日志进行分析
   * @param {Object} params
   * @param {string} params.log_content - 日志内容
   * @param {string} [params.log_type='dmesg'] - 日志类型
   * @param {string} [params.kernel_version] - 内核版本
   * @param {number} [params.top_k=5] - 返回 Top K 个补丁
   * @param {boolean} [params.enable_llm_explanation=true] - 是否启用 LLM 解释
   * @returns {Promise<{task_id: string, status: string}>}
   */
  async submit(params) {
    const { data } = await client.post('/analyze', params)
    return data
  },

  /**
   * 查询分析任务状态
   * @param {string} taskId
   * @returns {Promise<Object>}
   */
  async getStatus(taskId) {
    const { data } = await client.get(`/analyze/${taskId}`)
    return data
  },

  /**
   * 列出历史分析
   * @param {Object} params
   * @param {number} [params.page=1]
   * @param {number} [params.page_size=20]
   */
  async list(params = {}) {
    const { data } = await client.get('/analyze', { params })
    return data
  },
}
