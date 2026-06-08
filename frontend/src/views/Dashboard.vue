<template>
  <div class="dashboard">
    <h2 class="page-title">系统仪表盘</h2>
    <p class="text-muted mb-4">Linux内核补丁匹配系统 — 操作系统宕机补丁智能匹配系统</p>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="24" :sm="12" :lg="6" v-for="card in statCards" :key="card.label">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-card-inner">
            <div class="stat-icon" :style="{ backgroundColor: card.color + '20' }">
              <el-icon :size="24" :color="card.color">
                <component :is="card.icon" />
              </el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value" v-if="!statsStore.loading">
                <span v-if="card.loading" class="loading-text">—</span>
                <span v-else>{{ card.value }}</span>
              </div>
              <div class="stat-value" v-else>
                <el-skeleton animated style="width: 60px; height: 28px;" />
              </div>
              <div class="stat-label text-muted">{{ card.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表区域 -->
    <el-row :gutter="16" class="mt-4">
      <!-- 子系统分布 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span>内核子系统分布</span>
            <el-button text size="small" @click="statsStore.fetchStats()">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </template>
          <div class="chart-container" v-loading="statsStore.loading">
            <v-chart
              v-if="!statsStore.loading && statsStore.stats"
              :option="subsystemChartOption"
              autoresize
              style="height: 300px;"
            />
            <el-empty v-else description="暂无数据" />
          </div>
        </el-card>
      </el-col>

      <!-- Bug 类型分布 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover" class="chart-card">
          <template #header>
            <span>Bug 类型分布</span>
          </template>
          <div class="chart-container" v-loading="statsStore.loading">
            <v-chart
              v-if="!statsStore.loading && statsStore.stats"
              :option="bugTypeChartOption"
              autoresize
              style="height: 300px;"
            />
            <el-empty v-else description="暂无数据" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 系统信息 -->
    <el-row :gutter="16" class="mt-4">
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover">
          <template #header><span>系统信息</span></template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="向量库 Commit 数">
              {{ statsStore.stats?.total_commits?.toLocaleString() || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="已完成分析">
              {{ statsStore.stats?.total_analyses?.toLocaleString() || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="向量库大小">
              {{ statsStore.stats?.vector_db_size?.toLocaleString() || '—' }} 条
            </el-descriptions-item>
            <el-descriptions-item label="平均分析耗时">
              {{ formatDuration(statsStore.stats?.avg_analysis_ms) }}
            </el-descriptions-item>
            <el-descriptions-item label="服务运行时间">
              {{ formatDuration((statsStore.stats?.uptime_seconds || 0) * 1000) }}
            </el-descriptions-item>
            <el-descriptions-item label="数据更新">
              {{ formatRelativeTime(statsStore.lastUpdated) }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <!-- 快速入口 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="hover">
          <template #header><span>快速操作</span></template>
          <div class="quick-actions">
            <el-button type="primary" size="large" @click="$router.push('/analyze')">
              <el-icon><Search /></el-icon>
              宕机日志分析
            </el-button>
            <el-button size="large" @click="$router.push('/knowledge')">
              <el-icon><Collection /></el-icon>
              搜索补丁库
            </el-button>
            <el-button size="large" @click="$router.push('/history')">
              <el-icon><Clock /></el-icon>
              查看历史
            </el-button>
            <el-button size="large" @click="openApiDocs">
              <el-icon><Document /></el-icon>
              API 文档
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useStatsStore } from '@/stores/stats'
import { formatDuration, formatRelativeTime } from '@/utils/format'

use([PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const router = useRouter()
const statsStore = useStatsStore()

// ── 统计卡片 ────────────────────────────────────
const statCards = computed(() => [
  {
    label: '已索引 Commit',
    value: statsStore.stats?.total_commits?.toLocaleString() || '—',
    icon: 'Document',
    color: '#00d4ff',
    loading: statsStore.loading,
  },
  {
    label: '子系统覆盖',
    value: statsStore.stats?.subsystems?.length || '—',
    icon: 'Grid',
    color: '#00c853',
    loading: statsStore.loading,
  },
  {
    label: 'Bug 类型',
    value: statsStore.stats?.bug_types?.length || '—',
    icon: 'Warning',
    color: '#ff9800',
    loading: statsStore.loading,
  },
  {
    label: '已完成分析',
    value: statsStore.stats?.total_analyses?.toLocaleString() || '—',
    icon: 'Checked',
    color: '#9c27b0',
    loading: statsStore.loading,
  },
])

// ── 子系统饼图 ─────────────────────────────────
const subsystemChartOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { orient: 'vertical', right: 10, top: 'center', textStyle: { color: '#a0a0c0' } },
  series: [{
    type: 'pie',
    radius: ['45%', '75%'],
    center: ['40%', '50%'],
    avoidLabelOverlap: false,
    itemStyle: { borderRadius: 6, borderColor: '#0a0a1a', borderWidth: 2 },
    label: { show: false },
    emphasis: {
      label: { show: true, fontSize: 14, fontWeight: 'bold' },
    },
    data: (statsStore.stats?.subsystems || []).map(s => ({
      name: s.name,
      value: s.count,
    })),
  }],
}))

// ── Bug 类型柱状图 ─────────────────────────────
const bugTypeChartOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  xAxis: {
    type: 'value',
    axisLabel: { color: '#9090a0' },
    splitLine: { lineStyle: { color: '#2a2a40' } },
  },
  yAxis: {
    type: 'category',
    data: (statsStore.stats?.bug_types || []).map(b => b.name),
    axisLabel: { color: '#9090a0' },
  },
  series: [{
    type: 'bar',
    data: (statsStore.stats?.bug_types || []).map((b, i) => ({
      value: b.count,
      itemStyle: {
        color: ['#00d4ff', '#ff9800', '#00c853', '#ff3d3d', '#9c27b0', '#ff6d00'][i] || '#00d4ff',
        borderRadius: [0, 4, 4, 0],
      },
    })),
    barWidth: 20,
  }],
}))

function openApiDocs() {
  window.open('/api/docs', '_blank')
}

onMounted(() => {
  statsStore.fetchStats()
})
</script>

<style scoped>
.dashboard { max-width: 1400px; }

.page-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 4px;
  color: #fff;
}

.stats-row { margin-bottom: 8px; }

.stat-card { height: 100%; }
.stat-card-inner {
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #fff;
}
.stat-label {
  font-size: 13px;
  margin-top: 2px;
}

.chart-card :deep(.el-card__header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.chart-container { min-height: 300px; }

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
</style>
