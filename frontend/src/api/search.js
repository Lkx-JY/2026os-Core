import client from './client'

/**
 * 补丁知识库搜索 API
 */

export const searchApi = {
  /**
   * 搜索补丁
   * @param {Object} params
   * @param {string} params.query - 搜索关键词
   * @param {string} [params.subsystem] - 子系统过滤
   * @param {string} [params.bug_type] - Bug 类型过滤
   * @param {string} [params.kernel_version] - 内核版本过滤
   * @param {number} [params.page=1]
   * @param {number} [params.page_size=20]
   */
  async search(params) {
    const { data } = await client.post('/search', params)
    return data
  },

  /**
   * 获取 Commit 详情
   * @param {string} commitId
   */
  async getDetail(commitId) {
    const { data } = await client.get(`/search/${commitId}`)
    return data
  },

  /**
   * 获取所有子系统列表
   */
  async listSubsystems() {
    const { data } = await client.get('/search/subsystems/list')
    return data
  },

  /**
   * 获取所有 Bug 类型
   */
  async listBugTypes() {
    const { data } = await client.get('/search/bug-types/list')
    return data
  },
}
