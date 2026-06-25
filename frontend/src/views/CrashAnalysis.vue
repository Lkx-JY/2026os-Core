<template>
  <div class="crash-analysis">
    <h2 class="page-title">宕机日志分析</h2>
    <p class="text-muted mb-4">提交 Linux 内核宕机日志 (dmesg/vmcore)，自动分析根因并匹配上游补丁</p>

    <!-- 输入区域 -->
    <el-card shadow="hover" class="input-card" v-if="!showResult">
      <el-form :model="form" :rules="rules" ref="formRef" label-position="top">
        <el-form-item label="日志内容" prop="log_content">
          <el-input
            v-model="form.log_content"
            type="textarea"
            :rows="10"
            placeholder="请粘贴 dmesg / vmcore-dmesg 输出的宕机日志内容...
例如:
BUG: soft lockup - CPU#3 stuck for 23s! [swapper/3:0]
list_del corruption. prev->next should be ffff880123456789, but was ffff880987654321
Call Trace:
 [<ffffffff81234567>] list_del+0x12/0x30
 [<ffffffff81345678>] __slab_free+0xab/0x2c0"
            :disabled="analysisStore.submitting"
          />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="日志类型">
              <el-select v-model="form.log_type" style="width: 100%">
                <el-option label="dmesg" value="dmesg" />
                <el-option label="vmcore" value="vmcore" />
                <el-option label="Call Trace" value="calltrace" />
                <el-option label="原始日志" value="raw" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="内核版本 (可选)">
              <el-input v-model="form.kernel_version" placeholder="如 6.1.0" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="返回补丁数">
              <el-select v-model="form.top_k" style="width: 100%">
                <el-option :value="3" label="Top 3" />
                <el-option :value="5" label="Top 5" />
                <el-option :value="10" label="Top 10" />
                <el-option :value="20" label="Top 20" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item>
          <el-checkbox v-model="form.enable_llm_explanation">
            启用 LLM 分析解释 (返回自然语言分析报告)
          </el-checkbox>
        </el-form-item>

        <!-- ★ 大模型配置 — 用户选择付费方式 -->
        <el-form-item v-if="form.enable_llm_explanation" label="🤖 大模型配置">
          <el-card shadow="never" class="llm-config-card">
            <el-radio-group v-model="form.llm_mode" @change="onLlmModeChange">
              <el-radio value="free">
                <span style="font-weight: 500;">🆓 免费本地模型</span>
                <span class="text-muted text-sm ml-2">不产生费用，准确率稍低（需服务器安装 Ollama）</span>
              </el-radio>
              <el-radio value="own_key" class="mt-2">
                <span style="font-weight: 500;">🔑 使用我自己的 API Key</span>
                <span class="text-muted text-sm ml-2">高准确率，费用自理</span>
              </el-radio>
            </el-radio-group>

            <div v-if="form.llm_mode === 'own_key'" class="mt-3">
              <el-input
                v-model="form.user_api_key"
                type="password"
                show-password
                placeholder="sk-xxxxxxxx（支持 DeepSeek / OpenAI / Qwen）"
                clearable
              >
                <template #prepend>API Key</template>
              </el-input>
              <div class="text-muted text-sm mt-1" style="line-height: 1.6;">
                💡 Key 仅本次请求使用，不会存储到服务器。
                <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener">获取 DeepSeek Key →</a>
                &nbsp;|&nbsp;
                <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener">获取 OpenAI Key →</a>
              </div>
            </div>
          </el-card>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="analysisStore.submitting"
            @click="submitAnalysis"
            :icon="Search"
          >
            {{ analysisStore.submitting ? '正在提交...' : '开始分析' }}
          </el-button>
          <el-button size="large" @click="resetForm" :disabled="analysisStore.submitting">
            重置
          </el-button>
          <span class="text-muted ml-2 text-sm">分析过程约需 2-5 秒</span>
        </el-form-item>
      </el-form>

      <!-- 快速示例 -->
      <el-divider />
      <div class="quick-examples">
        <span class="text-sm text-muted mr-2">快速示例：</span>
        <el-tag
          v-for="example in quickExamples"
          :key="example.label"
          type="info"
          effect="plain"
          class="example-tag"
          @click="loadExample(example)"
        >
          {{ example.label }}
        </el-tag>
      </div>
    </el-card>

    <!-- 结果展示区域 -->
    <div v-if="showResult && currentTask" class="result-area fade-in-up">
      <!-- 进度条 (分析中) -->
      <el-card v-if="currentTask.status === 'running'" shadow="hover" class="progress-card">
        <div class="progress-header">
          <el-icon class="is-loading" :size="20"><Loading /></el-icon>
          <span>分析进行中...</span>
        </div>
        <el-progress
          :percentage="Math.round((currentTask.progress || 0) * 100)"
          :stroke-width="6"
          :color="'#1976D2'"
        />
        <div class="mt-4">
          <el-steps :active="activeStepIndex" align-center>
            <el-step title="日志解析" description="正则 + LLM 特征提取" />
            <el-step title="根因分析" description="Root Cause 抽象" />
            <el-step title="向量检索" description="Milvus/FAISS 召回" />
            <el-step title="LLM 解释" description="分析报告生成" />
          </el-steps>
        </div>
      </el-card>

      <!-- 分析完成 -->
      <template v-if="currentTask.status === 'completed' && currentTask.result">
        <!-- 根因分析 -->
        <el-card shadow="hover" class="section-card" v-if="currentTask.result.root_cause">
          <template #header>
            <div class="section-header">
              <span>🔍 根因分析</span>
              <el-tag
                :type="rootCauseTagType"
                size="large"
              >
                {{ bugTypeLabel(currentTask.result.root_cause.root_cause) }}
              </el-tag>
            </div>
          </template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="根因类型">
              {{ bugTypeLabel(currentTask.result.root_cause.root_cause) }}
            </el-descriptions-item>
            <el-descriptions-item label="受影响子系统">
              <el-tag size="small">{{ currentTask.result.root_cause.subsystem }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="置信度">
              <el-progress
                :percentage="Math.round(currentTask.result.root_cause.confidence * 100)"
                :stroke-width="16"
                :color="confidenceColor"
                style="width: 200px;"
              />
            </el-descriptions-item>
            <el-descriptions-item label="关键症状">
              <el-tag
                v-for="symptom in currentTask.result.root_cause.key_symptoms"
                :key="symptom"
                size="small"
                type="warning"
                effect="plain"
                class="mr-2"
              >
                {{ symptom }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <p class="mt-4">{{ currentTask.result.root_cause.summary }}</p>
        </el-card>

        <!-- 匹配补丁 -->
        <el-card shadow="hover" class="section-card mt-4">
          <template #header>
            <div class="section-header">
              <span>📋 匹配补丁 Top {{ currentTask.result.matched_patches?.length || 0 }}</span>
              <el-tag type="success">已按相关性排序</el-tag>
            </div>
          </template>

          <div
            v-for="patch in currentTask.result.matched_patches"
            :key="patch.rank"
            class="patch-item fade-in-up"
            :style="{ animationDelay: (patch.rank - 1) * 0.08 + 's' }"
          >
            <div class="patch-rank">
              <span class="rank-number">#{{ patch.rank }}</span>
              <el-progress
                :percentage="Math.round(patch.relevance_score * 100)"
                :stroke-width="8"
                :color="rankColor(patch.rank)"
                style="width: 80px;"
              />
            </div>

            <div class="patch-body">
              <h4 class="patch-title">
                {{ patch.commit.title }}
                <el-button
                  text
                  size="small"
                  @click="copyText(patch.commit.commit_id)"
                >
                  <el-icon><CopyDocument /></el-icon>
                  {{ shortHash(patch.commit.commit_id) }}
                </el-button>
              </h4>

              <p class="patch-message text-muted">{{ patch.commit.message }}</p>

              <div class="patch-meta">
                <el-tag size="small">{{ patch.commit.author }}</el-tag>
                <el-tag size="small" type="info">{{ patch.commit.date }}</el-tag>
                <el-tag size="small" type="warning" v-if="patch.diff_highlights?.length">
                  {{ patch.diff_highlights[0] }}
                </el-tag>
              </div>

              <div class="patch-reason mt-2">
                <el-alert
                  :title="patch.match_reason"
                  type="success"
                  :closable="false"
                  show-icon
                />
              </div>

              <!-- Diff 预览 -->
              <el-collapse class="mt-2">
                <el-collapse-item title="查看 Diff 预览">
                  <pre class="diff-preview"><code>{{ patch.commit.diff_preview }}</code></pre>
                </el-collapse-item>
              </el-collapse>

              <!-- 分数详情 -->
              <div class="patch-scores mt-2">
                <span class="text-sm text-muted">
                  召回: {{ formatPercent(patch.recall_score) }} |
                  重排: {{ formatPercent(patch.rerank_score) }} |
                  综合: {{ formatPercent(patch.relevance_score) }}
                </span>
              </div>
            </div>
          </div>

          <el-empty v-if="!currentTask.result.matched_patches?.length" description="未找到匹配的补丁" />
        </el-card>

        <!-- Mock 模式警告 -->
        <el-alert
          v-if="currentTask.result?.analysis_mode === 'mock'"
          title="⚠️ 演示模式 — 向量库未索引提交数据，当前返回模拟结果"
          type="warning"
          :closable="false"
          show-icon
          class="mt-4"
        >
          <template #default>
            请先运行索引脚本:
            <el-tag>python scripts/index_all_commits.py --repo-path &lt;linux-repo&gt; --limit 10000</el-tag>
          </template>
        </el-alert>

        <!-- LLM 解释 -->
        <el-card shadow="hover" class="section-card mt-4" v-if="currentTask.result.llm_explanation">
          <template #header>
            <span>🤖 LLM 分析报告</span>
          </template>
          <div class="llm-explanation" v-html="renderedExplanation"></div>
        </el-card>
      </template>

      <!-- 分析失败 -->
      <el-card v-if="currentTask.status === 'failed'" shadow="hover">
        <el-result
          icon="error"
          title="分析失败"
          :sub-title="currentTask.error || '未知错误'"
        >
          <template #extra>
            <el-button type="primary" @click="retryAnalysis">重试分析</el-button>
          </template>
        </el-result>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAnalysisStore } from '@/stores/analysis'
import {
  bugTypeLabel, shortHash, formatPercent, copyToClipboard,
} from '@/utils/format'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const route = useRoute()
const router = useRouter()
const analysisStore = useAnalysisStore()

// ── 表单 ────────────────────────────────────────
const formRef = ref(null)
const form = reactive({
  log_content: '',
  log_type: 'dmesg',
  kernel_version: '',
  top_k: 5,
  enable_llm_explanation: true,
  // LLM 配置 — 用户决定付费方式
  llm_mode: 'free',        // 'free' | 'own_key'
  user_api_key: '',
  user_api_base: '',
  user_api_model: '',
})

const rules = {
  log_content: [
    { required: true, message: '请输入宕机日志内容', trigger: 'blur' },
    { min: 10, message: '日志内容至少 10 个字符', trigger: 'blur' },
  ],
}

// ── 计算属性 ───────────────────────────────────
const currentTask = computed(() => analysisStore.currentTask)
const showResult = computed(() => currentTask.value !== null)

const activeStepIndex = computed(() => {
  if (!currentTask.value) return 0
  const steps = currentTask.value.result?.analysis_steps || []
  const completed = steps.filter(s => s.status === 'completed').length
  return completed
})

const rootCauseTagType = computed(() => {
  const rc = currentTask.value?.result?.root_cause?.root_cause
  if (!rc) return ''
  const types = {
    race_condition: 'danger',
    use_after_free: 'danger',
    null_pointer_dereference: 'warning',
    soft_lockup: 'warning',
    deadlock: 'danger',
    memory_corruption: 'danger',
  }
  return types[rc] || 'info'
})

const confidenceColor = computed(() => {
  const conf = currentTask.value?.result?.root_cause?.confidence
  if (conf == null) return '#78909c'
  if (conf >= 0.8) return '#4caf50'
  if (conf >= 0.6) return '#ff9800'
  return '#f44336'
})

const renderedExplanation = computed(() => {
  const text = currentTask.value?.result?.llm_explanation || ''
  return DOMPurify.sanitize(marked(text))
})

// ── 快速示例 ───────────────────────────────────
const quickExamples = [
  {
    label: 'list_del 竞态',
    content: `BUG: list_del corruption. prev->next should be ffff8800a1b2c3d4, but was ffff8800d4c3b2a1
------------[ cut here ]------------
kernel BUG at lib/list_debug.c:53!
Call Trace:
 [<ffffffff81234567>] __list_del_entry_valid+0x89/0xa0
 [<ffffffff81345678>] __slab_free+0xab/0x2c0
 [<ffffffff81456789>] kfree+0x12e/0x150`,
  },
  {
    label: 'Soft Lockup',
    content: `BUG: soft lockup - CPU#3 stuck for 23s! [swapper/3:0]
Kernel panic - not syncing: softlockup: hung tasks
Call Trace:
 [<ffffffff81098765>] watchdog_timer_fn+0x1a5/0x1d0
 [<ffffffff81123456>] __hrtimer_run_queues+0x10a/0x180
 [<ffffffff81134567>] hrtimer_interrupt+0xec/0x230`,
  },
  {
    label: 'Use-After-Free',
    content: `BUG: KASAN: use-after-free in kmem_cache_alloc+0x5f/0x170
Read of size 8 at addr ffff880123456789 by task kworker/1:2/1234
Call Trace:
 dump_stack+0x5c/0x80
 kasan_report+0x8e/0xb0
 kmem_cache_alloc+0x5f/0x170
Freed by task 5678:
 kfree+0x9d/0x1a0`,
  },
]

function loadExample(example) {
  form.log_content = example.content
}

function onLlmModeChange(mode) {
  if (mode === 'free') {
    form.user_api_key = ''
    form.user_api_base = ''
    form.user_api_model = ''
  }
}

// ── 提交分析 ───────────────────────────────────
async function submitAnalysis() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  try {
    const taskId = await analysisStore.submitAnalysis({
      log_content: form.log_content,
      log_type: form.log_type,
      kernel_version: form.kernel_version || undefined,
      top_k: form.top_k,
      enable_llm_explanation: form.enable_llm_explanation,
      user_api_key: form.llm_mode === 'own_key' ? form.user_api_key : undefined,
      user_api_base: form.llm_mode === 'own_key' ? form.user_api_base || undefined : undefined,
      user_api_model: form.llm_mode === 'own_key' ? form.user_api_model || undefined : undefined,
    })

    router.replace({ path: '/analyze', query: { task: taskId } })
    ElMessage.success('分析任务已提交，正在处理...')
  } catch (err) {
    ElMessage.error('提交分析失败: ' + (err.response?.data?.detail || err.message || '未知错误'))
  }
}

function resetForm() {
  formRef.value?.resetFields()
  analysisStore.currentTaskId = null
  router.replace('/analyze')
}

function retryAnalysis() {
  analysisStore.currentTaskId = null
}

function copyText(text) {
  copyToClipboard(text)
  ElMessage.success('已复制到剪贴板')
}

function rankColor(rank) {
  const colors = ['#1976D2', '#4caf50', '#ff9800', '#7c4dff', '#ff6d00']
  return colors[rank - 1] || '#78909c'
}

// ── 从 URL 恢复任务 ────────────────────────────
onMounted(() => {
  const taskId = route.query.task
  if (taskId && analysisStore.tasks[taskId]) {
    analysisStore.setCurrentTask(taskId)
    // 如果任务仍在运行，重新启动轮询（页面刷新不会丢失进度）
    if (analysisStore.tasks[taskId].status === 'running') {
      analysisStore.startPolling(taskId)
    }
  }
})

watch(() => route.query.task, (taskId) => {
  if (taskId && analysisStore.tasks[taskId]) {
    analysisStore.setCurrentTask(taskId)
    if (analysisStore.tasks[taskId].status === 'running') {
      analysisStore.startPolling(taskId)
    }
  }
})
</script>

<style scoped>
.crash-analysis { max-width: 1200px; }

.page-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 4px;
  color: var(--color-text);
}

.input-card { margin-bottom: 24px; }

.quick-examples {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.example-tag {
  cursor: pointer;
  transition: transform 0.15s;
}
.example-tag:hover {
  transform: translateY(-1px);
}

/* ── LLM 配置卡片 ────────────────────────────── */
.llm-config-card {
  background: rgba(25, 118, 210, 0.04) !important;
  border: 1px solid rgba(25, 118, 210, 0.12) !important;
}
.llm-config-card :deep(.el-radio) {
  display: flex;
  align-items: center;
  height: auto;
  padding: 4px 0;
  margin-right: 0;
}

/* ── 进度区域 ────────────────────────────────── */
.progress-card { text-align: center; padding: 24px 0; }
.progress-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 18px;
  margin-bottom: 24px;
}

/* ── 结果区域 ────────────────────────────────── */
.section-card { margin-bottom: 0; }
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.patch-item {
  display: flex;
  gap: 20px;
  padding: 20px 0;
  border-bottom: 1px solid var(--color-border);
}
.patch-item:last-child { border-bottom: none; }

.patch-rank {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 80px;
  padding-top: 4px;
}
.rank-number {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-primary);
}

.patch-body { flex: 1; }

.patch-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 8px;
}

.patch-meta {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.patch-scores { margin-top: 8px; }

.diff-preview {
  background: #f0f4f8;
  font-size: 12px;
  max-height: 200px;
  overflow-y: auto;
}

.llm-explanation {
  line-height: 1.8;
}
.llm-explanation :deep(h2) {
  font-size: 16px;
  margin-top: 16px;
  color: var(--color-primary);
}
.llm-explanation :deep(h3) {
  font-size: 14px;
  margin-top: 12px;
}
.llm-explanation :deep(strong) { color: var(--color-text); }
.llm-explanation :deep(code) {
  background: #f0f4f8;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: #e53935;
}
</style>
