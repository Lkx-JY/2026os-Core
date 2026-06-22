<template>
  <div class="history">
    <div class="page-header">
      <div>
        <h2 class="page-title">分析历史</h2>
        <p class="text-muted">查看历史宕机日志分析结果</p>
      </div>
      <el-button
        type="danger"
        text
        :disabled="!taskList.length"
        @click="confirmClear"
      >
        <el-icon><Delete /></el-icon>
        清空历史
      </el-button>
    </div>

    <!-- 统计 -->
    <el-row :gutter="16" class="mt-4">
      <el-col :span="6">
        <el-card shadow="hover" class="mini-stat">
          <div class="mini-stat-value">{{ taskList.length }}</div>
          <div class="mini-stat-label text-muted">总分析数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="mini-stat">
          <div class="mini-stat-value text-success">{{ completedCount }}</div>
          <div class="mini-stat-label text-muted">已完成</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="mini-stat">
          <div class="mini-stat-value text-warning">{{ runningCount }}</div>
          <div class="mini-stat-label text-muted">进行中</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="mini-stat">
          <div class="mini-stat-value text-danger">{{ failedCount }}</div>
          <div class="mini-stat-label text-muted">失败</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 任务列表 -->
    <el-card shadow="hover" class="mt-4">
      <el-table
        :data="taskList"
        style="width: 100%"
        @row-click="viewTask"
        v-loading="loading"
        empty-text="暂无分析记录"
      >
        <el-table-column label="任务 ID" width="180">
          <template #default="{ row }">
            <span class="text-mono text-sm">{{ row.task_id }}</span>
          </template>
        </el-table-column>

        <el-table-column label="日志类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">
              {{ row.request?.log_type || '—' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="日志预览" min-width="250">
          <template #default="{ row }">
            <span class="text-muted text-sm">
              {{ truncateText(row.log_preview || row.request?.log_content || '', 60) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="根因" width="160">
          <template #default="{ row }">
            <template v-if="row.result?.root_cause">
              <el-tag
                size="small"
                :type="bugTypeColor(row.result.root_cause.root_cause)"
              >
                {{ bugTypeLabel(row.result.root_cause.root_cause) }}
              </el-tag>
            </template>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="statusColor(row.status)"
              size="small"
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            <span class="text-sm text-muted">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click.stop="viewTask(row)">
              查看
            </el-button>
            <el-button text type="danger" size="small" @click.stop="deleteTask(row.task_id)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 详情对话框 -->
    <el-dialog
      v-model="detailVisible"
      title="分析详情"
      width="800px"
      destroy-on-close
    >
      <template v-if="detailTask?.result">
        <el-descriptions :column="2" border size="small" v-if="detailTask.result.root_cause">
          <el-descriptions-item label="根因类型">
            {{ bugTypeLabel(detailTask.result.root_cause.root_cause) }}
          </el-descriptions-item>
          <el-descriptions-item label="子系统">
            {{ detailTask.result.root_cause.subsystem }}
          </el-descriptions-item>
          <el-descriptions-item label="置信度">
            {{ formatPercent(detailTask.result.root_cause.confidence) }}
          </el-descriptions-item>
          <el-descriptions-item label="耗时">
            {{ formatDuration(detailTask.result.elapsed_ms) }}
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="mt-4 mb-2">匹配补丁</h4>
        <div v-for="patch in detailTask.result.matched_patches" :key="patch.rank" class="mb-2">
          <el-tag>{{ patch.rank }}.</el-tag>
          {{ patch.commit.title }}
          <span class="text-muted text-sm">({{ formatPercent(patch.relevance_score) }})</span>
        </div>

        <div class="mt-4" v-if="detailTask.result.llm_explanation">
          <h4 class="mb-2">LLM 分析</h4>
          <div v-html="renderedDetailExplanation"></div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useAnalysisStore } from '@/stores/analysis'
import {
  bugTypeLabel, bugTypeColor, statusLabel, statusColor,
  formatDateTime, formatPercent, formatDuration,
} from '@/utils/format'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const router = useRouter()
const analysisStore = useAnalysisStore()

const loading = ref(false)  // 配合 v-loading 使用，数据从 store 同步加载无需异步
const detailVisible = ref(false)
const detailTask = ref(null)

const taskList = computed(() => analysisStore.taskList)
const completedCount = computed(() => analysisStore.completedTasks.length)
const runningCount = computed(() => analysisStore.runningTasks.length)
const failedCount = computed(() =>
  taskList.value.filter(t => t.status === 'failed').length
)

const renderedDetailExplanation = computed(() => {
  return DOMPurify.sanitize(marked(detailTask.value?.result?.llm_explanation || ''))
})

function truncateText(text, maxLen) {
  if (!text) return ''
  return text.length > maxLen ? text.substring(0, maxLen).replace(/\n/g, ' ') + '...' : text.replace(/\n/g, ' ')
}

function viewTask(row) {
  analysisStore.setCurrentTask(row.task_id)
  router.push({ path: '/analyze', query: { task: row.task_id } })
}

function deleteTask(taskId) {
  analysisStore.clearTask(taskId)
  ElMessage.success('已删除')
}

function confirmClear() {
  ElMessageBox.confirm(
    '确认清空所有分析历史？此操作不可恢复。',
    '确认清空',
    { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
  ).then(() => {
    analysisStore.clearAll()
    ElMessage.success('已清空所有历史')
  }).catch(() => {})
}
</script>

<style scoped>
.history { max-width: 1400px; }

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 4px;
  color: #fff;
}

.mini-stat { text-align: center; }
.mini-stat-value { font-size: 28px; font-weight: 700; }
.mini-stat-label { font-size: 12px; margin-top: 2px; }
</style>
