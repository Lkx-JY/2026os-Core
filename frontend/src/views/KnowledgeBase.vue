<template>
  <div class="knowledge-base">
    <h2 class="page-title">补丁知识库</h2>
    <p class="text-muted mb-4">搜索 Linux Kernel 上游 Commit，浏览百万级补丁库</p>

    <!-- 搜索栏 -->
    <el-card shadow="hover" class="search-card">
      <div class="search-bar">
        <el-input
          v-model="searchQuery"
          placeholder="搜索 Commit 标题、内容、文件或修复标签..."
          size="large"
          clearable
          @keyup.enter="doSearch"
          @clear="doSearch"
          class="search-input"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
          <template #append>
            <el-button
              type="primary"
              :loading="searchStore.loading"
              @click="doSearch"
              :icon="Search"
            >
              搜索
            </el-button>
          </template>
        </el-input>
      </div>

      <!-- 过滤条件 -->
      <div class="filter-row mt-4">
        <el-select
          v-model="searchStore.filterSubsystem"
          placeholder="按子系统过滤"
          clearable
          @change="doSearch"
          style="width: 160px;"
        >
          <el-option
            v-for="opt in searchStore.subsystemOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>

        <el-select
          v-model="searchStore.filterBugType"
          placeholder="按 Bug 类型过滤"
          clearable
          @change="doSearch"
          style="width: 160px;"
        >
          <el-option
            v-for="opt in searchStore.bugTypeOptions"
            :key="opt.value"
            :label="bugTypeLabel(opt.value)"
            :value="opt.value"
          />
        </el-select>

        <el-button text @click="searchStore.resetFilters(); doSearch()">
          清除过滤
        </el-button>
      </div>
    </el-card>

    <!-- 搜索结果 -->
    <el-card shadow="hover" class="mt-4" v-loading="searchStore.loading">
      <!-- 搜索结果统计 -->
      <div class="result-header" v-if="searchStore.query">
        <span>
          搜索 "<strong>{{ searchStore.query }}</strong>"
          找到 <strong>{{ searchStore.total }}</strong> 条结果
        </span>
        <span class="text-muted text-sm">
          第 {{ searchStore.page }} / {{ searchStore.totalPages || 1 }} 页
        </span>
      </div>

      <!-- 分面统计 -->
      <div class="facets mb-4" v-if="searchStore.facets && searchStore.hasResults">
        <div v-if="Object.keys(searchStore.facets.subsystems || {}).length">
          <span class="text-sm text-muted">子系统：</span>
          <el-tag
            v-for="(count, name) in searchStore.facets.subsystems"
            :key="name"
            size="small"
            effect="plain"
            class="mr-2 facet-tag"
            @click="searchStore.filterSubsystem = name; doSearch()"
          >
            {{ name }} ({{ count }})
          </el-tag>
        </div>
        <div class="mt-2" v-if="Object.keys(searchStore.facets.bug_types || {}).length">
          <span class="text-sm text-muted">Bug 类型：</span>
          <el-tag
            v-for="(count, type) in searchStore.facets.bug_types"
            :key="type"
            size="small"
            effect="plain"
            class="mr-2 facet-tag"
            @click="searchStore.filterBugType = type; doSearch()"
          >
            {{ bugTypeLabel(type) }} ({{ count }})
          </el-tag>
        </div>
      </div>

      <!-- 结果列表 -->
      <div v-if="searchStore.hasResults">
        <div
          v-for="commit in searchStore.results"
          :key="commit.commit_id"
          class="commit-item"
          @click="showDetail(commit)"
        >
          <div class="commit-main">
            <h4 class="commit-title">
              {{ commit.title }}
              <el-tag
                size="small"
                :type="bugTypeColor(commit.bug_type)"
                v-if="commit.bug_type"
              >
                {{ bugTypeLabel(commit.bug_type) }}
              </el-tag>
            </h4>
            <p class="commit-message text-muted">{{ commit.message }}</p>
            <div class="commit-meta">
              <el-tag size="small">{{ commit.subsystem }}</el-tag>
              <span class="text-sm text-muted">{{ commit.author }}</span>
              <span class="text-sm text-muted">{{ commit.date }}</span>
              <span class="text-sm text-mono">{{ shortHash(commit.commit_id) }}</span>
            </div>
          </div>
          <div class="commit-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </div>
      </div>

      <el-empty v-else-if="searchStore.query" description="未找到匹配的 Commit" />
      <el-empty v-else description="输入关键词开始搜索补丁知识库" />

      <!-- 分页 -->
      <div class="mt-4 flex-center" v-if="searchStore.totalPages > 1">
        <el-pagination
          v-model:current-page="searchStore.page"
          :total="searchStore.total"
          :page-size="searchStore.pageSize"
          layout="prev, pager, next"
          @current-change="searchStore.setPage"
        />
      </div>
    </el-card>

    <!-- Commit 详情对话框 -->
    <el-dialog
      v-model="detailVisible"
      :title="detailCommit?.title || 'Commit 详情'"
      width="720px"
      destroy-on-close
    >
      <template v-if="detailCommit">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="Commit ID">
            <span class="text-mono">{{ detailCommit.commit_id }}</span>
            <el-button text size="small" @click="copyText(detailCommit.commit_id)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="作者">{{ detailCommit.author }}</el-descriptions-item>
          <el-descriptions-item label="日期">{{ detailCommit.date }}</el-descriptions-item>
          <el-descriptions-item label="子系统">
            <el-tag size="small">{{ detailCommit.subsystem }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Bug 类型" v-if="detailCommit.bug_type">
            <el-tag size="small" :type="bugTypeColor(detailCommit.bug_type)">
              {{ bugTypeLabel(detailCommit.bug_type) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="变更文件" :span="2">
            <el-tag
              v-for="f in detailCommit.files_changed"
              :key="f"
              size="small"
              effect="plain"
              class="mr-2"
            >
              {{ f }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="修复标签" :span="2" v-if="detailCommit.fix_tags?.length">
            <el-tag
              v-for="tag in detailCommit.fix_tags"
              :key="tag"
              size="small"
              type="warning"
              effect="plain"
              class="mr-2"
            >
              {{ tag }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="mt-4 mb-2">提交信息</h4>
        <p>{{ detailCommit.message }}</p>

        <h4 class="mt-4 mb-2">Diff 预览</h4>
        <pre class="diff-preview"><code>{{ detailCommit.diff_preview || '无 Diff 数据' }}</code></pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useSearchStore } from '@/stores/search'
import {
  bugTypeLabel, bugTypeColor, shortHash, copyToClipboard,
} from '@/utils/format'

const searchStore = useSearchStore()

const searchQuery = ref('')
const detailVisible = ref(false)
const detailCommit = ref(null)

function doSearch() {
  // 新搜索始终从第 1 页开始；setPage 内部也会调用 doSearch，
  // 但 KnowledgeBase 使用独立的 searchQuery，故分两步操作
  searchStore.setPage(1)
  if (searchStore.query !== searchQuery.value) {
    searchStore.doSearch(searchQuery.value)
  }
}

function showDetail(commit) {
  detailCommit.value = commit
  detailVisible.value = true
}

function copyText(text) {
  copyToClipboard(text)
  ElMessage.success('已复制到剪贴板')
}

onMounted(() => {
  searchStore.loadFilterOptions()
})
</script>

<style scoped>
.knowledge-base { max-width: 1200px; }

.page-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 4px;
  color: var(--color-text);
}

.search-card { margin-bottom: 0; }
.search-input { max-width: 800px; }

.filter-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 16px;
}

.facet-tag {
  cursor: pointer;
  transition: transform 0.15s;
}
.facet-tag:hover { transform: translateY(-1px); }

.commit-item {
  display: flex;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid var(--color-border);
  cursor: pointer;
  transition: background 0.15s;
}
.commit-item:hover { background: rgba(25, 118, 210, 0.06); }
.commit-item:last-child { border-bottom: none; }

.commit-main { flex: 1; }
.commit-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 6px;
}
.commit-message {
  font-size: 13px;
  line-height: 1.5;
  margin-bottom: 8px;
}
.commit-meta {
  display: flex;
  gap: 12px;
  align-items: center;
}

.commit-arrow {
  color: var(--color-text-muted);
  padding: 0 8px;
}

.diff-preview {
  background: #f0f4f8;
  font-size: 12px;
  max-height: 300px;
  overflow-y: auto;
}
</style>
