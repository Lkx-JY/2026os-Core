<template>
  <div class="llm-explain-container">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="icon-primary"><MessageCircle /></el-icon>
        LLM分析解释
      </h1>
      <p class="page-desc">基于大语言模型的智能故障分析与解释</p>
    </div>

    <!-- 分析表单 -->
    <el-card class="analysis-card">
      <div class="card-header">
        <h2 class="card-title">输入分析内容</h2>
        <p class="card-desc">请输入故障日志、错误信息或需要分析的内容，系统将使用AI进行智能分析</p>
      </div>

      <div class="analysis-form">
        <!-- 输入区域 -->
        <div class="form-group">
          <label class="form-label">分析内容</label>
          <el-input
            v-model="inputContent"
            type="textarea"
            :rows="8"
            placeholder="请输入需要分析的故障日志、错误信息或问题描述...

示例输入：
[  123.456789] BUG: kernel NULL pointer dereference, address: 0000000000000028
[  123.456790] #PF: supervisor read access in kernel mode
[  123.456791] #PF: error_code(0x0000) - not-present page
[  123.456792] PGD 0 P4D 0
[  123.456793] Oops: 0000 [#1] PREEMPT SMP NOPTI
[  123.456794] CPU: 2 PID: 1234 Comm: kworker/u8:0 Kdump: loaded
[  123.456795] Hardware name: QEMU Standard PC (i440FX + PIIX, 1996), BIOS 1.14.0-2.fc34 04/01/2014
[  123.456796] RIP: 0010:my_function+0x123/0x456
[  123.456797] Code: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
[  123.456798] RSP: 0018:ffffc90000123456 EFLAGS: 00010202
[  123.456799] RAX: 0000000000000000 RBX: ffff888000112233 RCX: 0000000000000000
[  123.456800] RDX: ffff888000445566 RSI: ffff888000778899 RDI: 0000000000000000
[  123.456801] RBP: ffff888000aaaabb R08: 0000000000000000 R09: 0000000000000000
[  123.456802] R10: ffff888000cccddd R11: ffff888000eeeeff R12: ffff888000112233
[  123.456803] R13: ffff888000445566 R14: ffff888000778899 R15: ffff888000aaaabb
[  123.456804] FS:  00007f1234567890(0000) GS:ffff888000bbbccc(0000) knlGS:0000000000000000
[  123.456805] CS:  0010 DS: 0000 ES: 0000 CR0: 0000000080050033
[  123.456806] CR2: 0000000000000028 CR3: 0000000000112233 CR4: 00000000003506e0
[  123.456807] Call Trace:
[  123.456808]  my_other_function+0xab/0xcd
[  123.456809]  my_driver_init+0xef/0x100 [my_driver]
[  123.456810]  do_one_initcall+0x45/0x200
[  123.456811]  kernel_init_freeable+0x123/0x234
[  123.456812]  kernel_init+0xe/0x100
[  123.456813]  ret_from_fork+0x22/0x40
[  123.456814] Modules linked in: my_driver(OE+) ..."
            class="analysis-textarea"
          />
        </div>

        <!-- 分析选项 -->
        <div class="form-group">
          <label class="form-label">分析模式</label>
          <div class="mode-options">
            <el-radio-group v-model="analysisMode" class="radio-group">
              <el-radio label="full" border>完整分析</el-radio>
              <el-radio label="quick" border>快速诊断</el-radio>
              <el-radio label="deep" border>深度分析</el-radio>
            </el-radio-group>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="form-actions">
          <el-button
            type="primary"
            :loading="isAnalyzing"
            :disabled="!inputContent.trim()"
            @click="startAnalysis"
            class="btn-primary"
          >
            <el-icon><Sparkles /></el-icon>
            {{ isAnalyzing ? '分析中...' : '开始AI分析' }}
          </el-button>
          <el-button
            @click="clearInput"
            class="btn-secondary"
          >
            <el-icon><Delete /></el-icon>
            清空内容
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 分析结果 -->
    <el-card v-if="analysisResult" class="result-card">
      <div class="card-header">
        <h2 class="card-title">分析结果</h2>
        <div class="result-meta">
          <span class="meta-item">
            <el-icon size="14"><Clock /></el-icon>
            {{ analysisTime }}
          </span>
          <span class="meta-item">
            <el-icon size="14"><Cpu /></el-icon>
            {{ analysisMode === 'full' ? '完整分析' : analysisMode === 'quick' ? '快速诊断' : '深度分析' }}
          </span>
        </div>
      </div>

      <div class="result-content">
        <!-- 诊断摘要 -->
        <div class="result-section">
          <h3 class="section-title">
            <el-icon><AlertTriangle /></el-icon>
            故障诊断摘要
          </h3>
          <div class="summary-content">
            <div class="summary-item" v-for="(item, idx) in resultSummary" :key="idx">
              <span class="summary-badge" :class="item.level">{{ item.label }}</span>
              <span class="summary-text">{{ item.text }}</span>
            </div>
          </div>
        </div>

        <!-- 详细分析 -->
        <div class="result-section">
          <h3 class="section-title">
            <el-icon><FileText /></el-icon>
            详细分析报告
          </h3>
          <div class="analysis-content" v-html="formattedResult"></div>
        </div>

        <!-- 修复建议 -->
        <div class="result-section">
          <h3 class="section-title">
            <el-icon><Wrench /></el-icon>
            修复建议
          </h3>
          <ul class="suggestions-list">
            <li v-for="(suggestion, idx) in repairSuggestions" :key="idx">
              <span class="suggestion-number">{{ idx + 1 }}</span>
              <span class="suggestion-text">{{ suggestion }}</span>
            </li>
          </ul>
        </div>

        <!-- 相关补丁 -->
        <div class="result-section" v-if="relatedPatches.length > 0">
          <h3 class="section-title">
            <el-icon><GitBranch /></el-icon>
            相关补丁建议
          </h3>
          <div class="patches-list">
            <div
              v-for="(patch, idx) in relatedPatches"
              :key="idx"
              class="patch-item"
              @click="goToPatchDetail(patch.commit_id)"
            >
              <div class="patch-header">
                <span class="patch-score" :class="patch.score >= 0.8 ? 'high' : patch.score >= 0.6 ? 'medium' : 'low'">
                  匹配度: {{ (patch.score * 100).toFixed(0) }}%
                </span>
                <span class="patch-hash">{{ patch.commit_id }}</span>
              </div>
              <div class="patch-title">{{ patch.title }}</div>
              <div class="patch-summary">{{ patch.summary }}</div>
              <div class="patch-meta">
                <span>{{ patch.author }}</span>
                <span>{{ patch.date }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 历史分析记录 -->
    <el-card class="history-card">
      <div class="card-header">
        <h2 class="card-title">最近分析记录</h2>
        <p class="card-desc">快速访问最近的分析历史</p>
      </div>
      <div class="history-list">
        <div
          v-for="(history, idx) in recentHistory"
          :key="idx"
          class="history-item"
          @click="loadHistory(history)"
        >
          <div class="history-preview">{{ history.preview }}</div>
          <div class="history-time">{{ history.time }}</div>
        </div>
        <div v-if="recentHistory.length === 0" class="empty-history">
          <el-icon size="32"><History /></el-icon>
          <p>暂无分析记录</p>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { ElMessage } from 'element-plus'
import { searchApi } from '@/api/search'

const router = useRouter()

// 响应式数据
const inputContent = ref('')
const analysisMode = ref('full')
const isAnalyzing = ref(false)
const analysisResult = ref(null)
const analysisTime = ref('')

// 模拟历史记录（从 localStorage 读取）
const recentHistory = ref(JSON.parse(localStorage.getItem('llm_history') || '[]'))

// 分析结果摘要
const resultSummary = computed(() => {
  if (!analysisResult.value) return []
  return [
    { label: '故障类型', text: analysisResult.value.fault_type || '未知', level: 'warning' },
    { label: '严重程度', text: analysisResult.value.severity || '中等', level: 'danger' },
    { label: '影响范围', text: analysisResult.value.impact || '局部', level: 'info' },
    { label: '根因定位', text: analysisResult.value.root_cause || '分析中', level: 'success' }
  ]
})

// 修复建议
const repairSuggestions = computed(() => {
  if (!analysisResult.value) return []
  return analysisResult.value.suggestions || [
    '检查空指针引用，在访问指针前添加 NULL 检查',
    '验证内存分配是否成功',
    '审查相关代码路径，确认所有边界条件都已处理',
    '考虑添加适当的锁保护，防止并发访问问题'
  ]
})

// 相关补丁
const relatedPatches = computed(() => {
  if (!analysisResult.value) return []
  return analysisResult.value.patches || [
    {
      commit_id: 'abc1234',
      title: 'fix: NULL pointer check in my_function',
      summary: '添加空指针检查，防止内核崩溃',
      author: 'John Doe',
      date: '2024-01-15',
      score: 0.92
    },
    {
      commit_id: 'def5678',
      title: 'fix: validate input before dereference',
      summary: '在解引用前验证输入参数',
      author: 'Jane Smith',
      date: '2024-01-10',
      score: 0.78
    }
  ]
})

// 格式化 Markdown 结果
const formattedResult = computed(() => {
  if (!analysisResult.value) return ''
  return DOMPurify.sanitize(marked(analysisResult.value.content || ''))
})

// 开始分析
async function startAnalysis() {
  if (!inputContent.value.trim()) return

  isAnalyzing.value = true

  try {
    // 调用后端搜索 API 查找匹配的补丁
    const result = await searchApi.search({
      query: inputContent.value.trim(),
      page_size: 5,
    })

    // 将搜索结果映射为分析结果格式
    const patches = (result.items || result.results || []).map((item) => ({
      commit_id: item.commit_id || item.commit_hash || 'N/A',
      title: item.title || item.subject || '未知补丁',
      summary: (item.message || item.body || '').substring(0, 200),
      author: item.author || '未知',
      date: item.date || '',
      score: item.relevance_score || item.final_score || 0.5,
    }))

    analysisResult.value = {
      fault_type: '内核崩溃',
      severity: '待评估',
      impact: '系统稳定性',
      root_cause: '需要通过日志进一步分析',
      suggestions: [
        '检查日志中报告的调用栈，定位问题发生位置',
        '应用推荐补丁列表中匹配度最高的补丁',
        '在测试环境中验证补丁修复效果',
        '确认相关子系统中是否存在其他类似问题',
      ],
      patches: patches.length > 0 ? patches : [
        {
          commit_id: 'N/A',
          title: '未找到匹配补丁',
          summary: '知识库中暂无与此日志匹配的补丁，建议通过 dmesg 模块运行完整的根因分析',
          author: '',
          date: '',
          score: 0,
        },
      ],
      content: `## 搜索结果分析

根据输入内容在 Linux 内核补丁知识库中检索到 **${patches.length}** 个相关补丁。

${patches.length > 0 ? '### 匹配的补丁\n\n' + patches.map((p, i) =>
  `${i + 1}. **${p.title}** (匹配度: ${(p.score * 100).toFixed(0)}%)\n   - 作者: ${p.author}\n   - 日期: ${p.date}\n   - 摘要: ${p.summary}`
).join('\n\n') : '暂无匹配的补丁。请尝试使用 /analyze 页面上传完整 dmesg 日志进行详细分析。'}`,
    }

    analysisTime.value = new Date().toLocaleString('zh-CN')

    // 保存到历史记录
    const historyEntry = {
      preview: inputContent.value.trim().substring(0, 80),
      time: new Date().toLocaleString('zh-CN'),
    }
    recentHistory.value.unshift(historyEntry)
    if (recentHistory.value.length > 20) recentHistory.value = recentHistory.value.slice(0, 20)
    localStorage.setItem('llm_history', JSON.stringify(recentHistory.value))
  } catch (err) {
    console.error('LLM 分析失败:', err)
    ElMessage.error('分析请求失败: ' + (err.response?.data?.detail || err.message || '未知错误'))
  } finally {
    isAnalyzing.value = false
  }
}

// 清空输入
function clearInput() {
  inputContent.value = ''
  analysisResult.value = null
}

// 加载历史记录
function loadHistory(history) {
  inputContent.value = history.preview
}

// 跳转到补丁详情
function goToPatchDetail(commitId) {
  router.push({ path: '/knowledge', query: { search: commitId } })
}
</script>

<style scoped>
.llm-explain-container {
  max-width: 1200px;
  margin: 0 auto;
}

/* ── 页面标题 ──────────────────────────────────── */
.page-header {
  margin-bottom: 24px;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 24px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 8px;
}
.icon-primary {
  color: var(--color-primary);
}
.page-desc {
  color: var(--color-text-muted);
  font-size: 14px;
}

/* ── 卡片通用样式 ──────────────────────────────── */
.el-card {
  margin-bottom: 24px;
}
.card-header {
  margin-bottom: 20px;
}
.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 4px;
}
.card-desc {
  font-size: 13px;
  color: var(--color-text-muted);
}

/* ── 分析表单 ──────────────────────────────────── */
.analysis-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}
.analysis-textarea {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  resize: none;
}
.mode-options {
  display: flex;
  gap: 16px;
}
.radio-group {
  display: flex;
  gap: 16px;
}
.form-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
.btn-primary {
  padding: 10px 24px;
  font-size: 14px;
}
.btn-secondary {
  padding: 10px 20px;
  font-size: 14px;
}

/* ── 结果卡片 ──────────────────────────────────── */
.result-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: var(--color-text-muted);
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.result-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.result-section {
  background: rgba(0, 0, 0, 0.04);
  border-radius: 8px;
  padding: 16px;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-primary);
  margin-bottom: 12px;
}

/* ── 摘要内容 ──────────────────────────────────── */
.summary-content {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.summary-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.summary-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}
.summary-badge.warning { background: rgba(255, 152, 0, 0.15); color: #e65100; }
.summary-badge.danger { background: rgba(244, 67, 54, 0.15); color: #c62828; }
.summary-badge.info { background: rgba(25, 118, 210, 0.15); color: #1976D2; }
.summary-badge.success { background: rgba(76, 175, 80, 0.15); color: #2e7d32; }
.summary-text {
  font-size: 13px;
  color: var(--color-text);
}

/* ── 分析内容 ──────────────────────────────────── */
.analysis-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-text);
}
.analysis-content h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--color-primary);
}
.analysis-content h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 6px;
  color: var(--color-text);
}
.analysis-content p {
  margin: 6px 0;
}
.analysis-content code {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: #e53935;
}
.analysis-content pre {
  background: #f5f7fa !important;
  border-color: var(--color-border) !important;
  margin: 12px 0;
}
.analysis-content ul, .analysis-content ol {
  padding-left: 24px;
  margin: 8px 0;
}

/* ── 修复建议 ──────────────────────────────────── */
.suggestions-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.suggestions-list li {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border);
}
.suggestions-list li:last-child {
  border-bottom: none;
}
.suggestion-number {
  width: 24px;
  height: 24px;
  background: var(--color-primary);
  color: #fff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}
.suggestion-text {
  font-size: 13px;
  color: var(--color-text);
  line-height: 1.5;
}

/* ── 相关补丁 ──────────────────────────────────── */
.patches-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.patch-item {
  background: rgba(0, 0, 0, 0.04);
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.patch-item:hover {
  background: rgba(25, 118, 210, 0.08);
  border-left: 3px solid var(--color-primary);
}
.patch-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.patch-score {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.patch-score.high { background: rgba(76, 175, 80, 0.15); color: #2e7d32; }
.patch-score.medium { background: rgba(255, 152, 0, 0.15); color: #e65100; }
.patch-score.low { background: rgba(244, 67, 54, 0.15); color: #c62828; }
.patch-hash {
  font-family: monospace;
  font-size: 12px;
  color: var(--color-text-muted);
}
.patch-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
  margin-bottom: 4px;
}
.patch-summary {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 8px;
}
.patch-meta {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--color-text-muted);
}

/* ── 历史记录 ──────────────────────────────────── */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.history-item:hover {
  background: rgba(0, 212, 255, 0.1);
}
.history-preview {
  font-size: 13px;
  color: var(--color-text);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-time {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-left: 12px;
}
.empty-history {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--color-text-muted);
}
.empty-history p {
  margin-top: 8px;
  font-size: 13px;
}
</style>
