<template>
  <div class="crash-analysis">
    <h2 class="page-title">宕机日志分析</h2>
    <p class="text-muted mb-4">提交 Linux 内核宕机日志 (dmesg/vmcore)，自动分析根因并匹配上游补丁</p>

    <!-- ★ 输入区域 — 始终可见，有结果时折叠为紧凑栏 -->
    <el-card shadow="hover" class="input-card">
      <!-- 有结果时：折叠为紧凑操作栏 -->
      <div v-if="showResult" class="compact-input-bar">
        <span class="compact-input-hint">📝 输入新的宕机日志进行下一次分析</span>
        <el-button type="primary" @click="resetForm" :icon="Plus">
          新建分析
        </el-button>
      </div>

      <!-- 无结果时：完整表单 -->
      <template v-else>
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
      </template>
    </el-card>

    <!-- 结果展示区域 -->
    <div v-if="showResult && currentTask" class="result-area fade-in-up">
      <!-- 操作栏 — 新建分析 / 查看历史 -->
      <div class="result-toolbar">
        <el-button type="primary" @click="resetForm" :icon="Plus">
          新建分析
        </el-button>
        <el-button @click="$router.push('/history')" :icon="Clock">
          查看历史
        </el-button>
      </div>

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

          <!-- ★ Possible Causes — 第二层根因抽象 -->
          <template v-if="currentTask.result.root_cause.possible_causes?.length">
            <el-divider />
            <div class="possible-causes-section">
              <div class="evidence-header">
                <span>🔬 可能的深层原因 (Possible Causes)</span>
                <el-tag size="small" type="warning" effect="plain">Layer 2 — 根因抽象</el-tag>
              </div>
              <p class="text-sm text-muted mb-2">
                {{ currentTask.result.root_cause.root_cause }} 是 Bug 类型 (发生了什么)。
                以下列出可能导致该 Bug 的深层原因 (为什么会发生)：
              </p>
              <ul class="possible-causes-list">
                <li v-for="(cause, ci) in currentTask.result.root_cause.possible_causes" :key="'cause-'+ci">
                  {{ cause }}
                </li>
              </ul>
            </div>
          </template>

          <!-- ★ Confidence Breakdown — 置信度拆解 -->
          <template v-if="currentTask.result.root_cause.confidence_breakdown">
            <el-divider />
            <div class="confidence-breakdown-section">
              <div class="evidence-header">
                <span>📊 置信度拆解 (Confidence Breakdown)</span>
                <el-tag size="small" type="info" effect="plain">为什么是 {{ Math.round(currentTask.result.root_cause.confidence * 100) }}%？</el-tag>
              </div>
              <div class="confidence-grid">
                <div class="confidence-item">
                  <span class="conf-label">Rule Match</span>
                  <el-progress
                    :percentage="currentTask.result.root_cause.confidence_breakdown.rule_match"
                    :stroke-width="10" color="#1976D2" style="flex: 1; margin: 0 8px;"
                  />
                  <span class="conf-pct">+{{ currentTask.result.root_cause.confidence_breakdown.rule_match }}%</span>
                </div>
                <div class="confidence-item">
                  <span class="conf-label">Fault Address</span>
                  <el-progress
                    :percentage="currentTask.result.root_cause.confidence_breakdown.fault_address_pattern"
                    :stroke-width="10" color="#388E3C" style="flex: 1; margin: 0 8px;"
                  />
                  <span class="conf-pct">+{{ currentTask.result.root_cause.confidence_breakdown.fault_address_pattern }}%</span>
                </div>
                <div class="confidence-item">
                  <span class="conf-label">Subsystem</span>
                  <el-progress
                    :percentage="currentTask.result.root_cause.confidence_breakdown.subsystem_match"
                    :stroke-width="10" color="#F57C00" style="flex: 1; margin: 0 8px;"
                  />
                  <span class="conf-pct">+{{ currentTask.result.root_cause.confidence_breakdown.subsystem_match }}%</span>
                </div>
                <div class="confidence-item">
                  <span class="conf-label">Call Trace</span>
                  <el-progress
                    :percentage="currentTask.result.root_cause.confidence_breakdown.call_trace_evidence"
                    :stroke-width="10" color="#7C4DFF" style="flex: 1; margin: 0 8px;"
                  />
                  <span class="conf-pct">
                    {{ currentTask.result.root_cause.confidence_breakdown.call_trace_evidence > 0 ? '+' : '' }}{{ currentTask.result.root_cause.confidence_breakdown.call_trace_evidence }}%
                    <el-tag v-if="currentTask.result.root_cause.confidence_breakdown.call_trace_evidence === 0" size="small" type="info" style="margin-left: 4px;">缺失</el-tag>
                  </span>
                </div>
                <div class="confidence-item">
                  <span class="conf-label">Historical Similarity</span>
                  <el-progress
                    :percentage="currentTask.result.root_cause.confidence_breakdown.historical_similarity"
                    :stroke-width="10" color="#009688" style="flex: 1; margin: 0 8px;"
                  />
                  <span class="conf-pct">+{{ currentTask.result.root_cause.confidence_breakdown.historical_similarity }}%</span>
                </div>
                <div class="confidence-item total">
                  <span class="conf-label" style="font-weight: 700;">Total</span>
                  <el-progress
                    :percentage="Math.round(currentTask.result.root_cause.confidence * 100)"
                    :stroke-width="14" color="#E53935" style="flex: 1; margin: 0 8px;"
                  />
                  <span class="conf-pct" style="font-weight: 700;">= {{ Math.round(currentTask.result.root_cause.confidence * 100) }}%</span>
                </div>
              </div>
            </div>
          </template>

          <!-- ★ 根因证据 (Root Cause Evidence) — 可解释性增强 -->
          <template v-if="currentTask.result.root_cause.evidence">
            <el-divider />
            <div class="evidence-section">
              <div class="evidence-header">
                <span>📋 根因证据 (Root Cause Evidence)</span>
                <el-tag size="small" type="info" effect="plain">LLM 引用依据</el-tag>
              </div>
              <div class="evidence-grid">
                <div class="evidence-item" v-if="currentTask.result.root_cause.evidence.panic_keyword">
                  <el-icon color="#4caf50"><CircleCheck /></el-icon>
                  <span class="evidence-label">panic_keyword:</span>
                  <span class="evidence-value">{{ currentTask.result.root_cause.evidence.panic_keyword }}</span>
                </div>
                <div class="evidence-item" v-if="currentTask.result.root_cause.evidence.fault_address">
                  <el-icon color="#4caf50"><CircleCheck /></el-icon>
                  <span class="evidence-label">fault_address:</span>
                  <code class="evidence-code">{{ currentTask.result.root_cause.evidence.fault_address }}</code>
                </div>
                <div class="evidence-item" v-if="currentTask.result.root_cause.evidence.error_code">
                  <el-icon color="#4caf50"><CircleCheck /></el-icon>
                  <span class="evidence-label">error_code:</span>
                  <code class="evidence-code">{{ currentTask.result.root_cause.evidence.error_code }}</code>
                </div>
                <div class="evidence-item" v-if="currentTask.result.root_cause.evidence.subsystem">
                  <el-icon color="#4caf50"><CircleCheck /></el-icon>
                  <span class="evidence-label">subsystem:</span>
                  <span class="evidence-value">{{ currentTask.result.root_cause.evidence.subsystem }}</span>
                </div>
                <div class="evidence-item">
                  <el-icon color="#4caf50"><CircleCheck /></el-icon>
                  <span class="evidence-label">confidence:</span>
                  <el-progress
                    :percentage="Math.round((currentTask.result.root_cause.evidence.confidence || 0) * 100)"
                    :stroke-width="6" :color="'#4caf50'" style="width: 100px; display: inline-flex;"
                  />
                </div>
                <div class="evidence-item" v-if="currentTask.result.root_cause.evidence.matched_rule_id">
                  <el-icon color="#1976D2"><CircleCheck /></el-icon>
                  <span class="evidence-label">matched_rule:</span>
                  <el-tag size="small" type="primary">
                    {{ currentTask.result.root_cause.evidence.matched_rule_id }}
                  </el-tag>
                  <span class="evidence-value ml-2" v-if="currentTask.result.root_cause.evidence.matched_rule_name">
                    {{ currentTask.result.root_cause.evidence.matched_rule_name }}
                  </span>
                </div>
                <div class="evidence-item"
                     v-for="(func, idx) in (currentTask.result.root_cause.evidence.trace_functions || []).slice(0, 5)"
                     :key="'tf-'+idx">
                  <el-icon color="#ff9800"><CircleCheck /></el-icon>
                  <span class="evidence-label">trace_function:</span>
                  <code class="evidence-code">{{ func }}</code>
                </div>
              </div>

              <!-- LLM 引用提示 -->
              <el-alert type="info" :closable="false" class="mt-3" show-icon>
                <template #title>
                  依据以上 Evidence，进入 Patch 检索阶段
                </template>
              </el-alert>
            </div>
          </template>
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
              <el-tag :type="patch.rank === 1 ? 'danger' : 'info'" size="small">
                {{ patch.rank === 1 ? 'Top Candidate' : 'Candidate' }}
              </el-tag>
            </div>

            <div class="patch-body">
              <!-- ═══ Zone 1: 基本信息 ═══ -->
              <h4 class="patch-title">
                {{ patch.commit.title }}
                <el-button text size="small" @click="copyText(patch.commit.commit_id)">
                  <el-icon><CopyDocument /></el-icon>
                  {{ shortHash(patch.commit.commit_id) }}
                </el-button>
              </h4>
              <div class="patch-meta">
                <el-tag size="small" type="info">{{ patch.commit.author }}</el-tag>
                <el-tag size="small" type="info">{{ patch.commit.date }}</el-tag>
                <el-tag size="small" v-if="patch.commit.subsystem && patch.commit.subsystem !== 'unknown'">{{ patch.commit.subsystem }}</el-tag>
                <el-tag size="small" type="warning" v-if="patch.commit.bug_type && patch.commit.bug_type !== 'unknown'">{{ patch.commit.bug_type }}</el-tag>
              </div>

              <!-- ═══ Zone 0: 为什么不是 #1 (Why-Not) ═══ -->
              <el-alert
                v-if="patch.rank >= 2 && patch.why_not_explanation"
                type="warning"
                :closable="false"
                class="why-not-alert mb-3"
              >
                <template #title>
                  💭 为什么不是 #1？
                </template>
                <template #default>
                  <div class="why-not-content">
                    <div v-if="patch.why_not_explanation.same_aspects?.length" class="mb-2">
                      <span class="text-sm" style="color: #4caf50;">✓ 共同点：</span>
                      <ul class="why-not-list same">
                        <li v-for="(aspect, ai) in patch.why_not_explanation.same_aspects" :key="'same-'+ai">
                          {{ aspect }}
                        </li>
                      </ul>
                    </div>
                    <div>
                      <span class="text-sm" style="color: #f44336;">✗ 差异点：</span>
                      <ul class="why-not-list different">
                        <li v-for="(aspect, di) in patch.why_not_explanation.different_aspects" :key="'diff-'+di">
                          {{ aspect }}
                        </li>
                      </ul>
                    </div>
                    <p class="text-sm text-muted mt-2" v-if="patch.why_not_explanation.ranking_reason">
                      <strong>结论：</strong>{{ patch.why_not_explanation.ranking_reason }}
                    </p>
                  </div>
                </template>
              </el-alert>

              <!-- ═══ Zone 2: Matching Evidence 匹配依据 ═══ -->
              <div class="matching-evidence mt-3">
                <div class="evidence-title">Matching Evidence</div>
                <div class="evidence-items">
                  <span class="evidence-item" v-if="patch.match_reason?.includes('subsystem') || patch.commit.subsystem">
                    <span class="evidence-check">✓</span> Same Subsystem
                  </span>
                  <span class="evidence-item" v-if="patch.match_reason?.includes('bug') || patch.commit.bug_type">
                    <span class="evidence-check">✓</span> Same Bug Type
                  </span>
                  <span class="evidence-item" v-if="patch.recall_score > 0">
                    <span class="evidence-check">✓</span> High Semantic Similarity
                  </span>
                  <!-- Cross Encoder score (not rank) -->
                  <span class="evidence-item" v-if="patch.reranker_score > 0">
                    <span class="evidence-check">✓</span> Cross Encoder: {{ (patch.reranker_score * 100).toFixed(1) }}%
                  </span>
                  <span class="evidence-item" v-if="patch.match_reason">
                    <span class="evidence-check">✓</span> {{ patch.match_reason }}
                  </span>
                </div>
              </div>

              <!-- ═══ Zone 3: Matching Score 评分 ═══ -->
              <div class="matching-score mt-3">
                <div class="score-item">
                  <span class="score-label">Embedding Similarity</span>
                  <span class="score-value">{{ patch.recall_score?.toFixed(3) || '—' }}</span>
                </div>
                <div class="score-item">
                  <span class="score-label">Cross Encoder Score</span>
                  <span class="score-value">{{ patch.reranker_score?.toFixed(3) || '—' }}</span>
                </div>
                <div class="score-item final-score">
                  <span class="score-label">Final Score</span>
                  <span class="score-value">
                    {{ formatScore(patch.relevance_score) }}
                    <small class="text-muted" style="font-size: 10px; display: block;">
                      {{ scoreInterpretation(patch.relevance_score) }}
                    </small>
                  </span>
                </div>
              </div>

              <!-- ═══ Zone 3.5: 多维分数明细 (Score Breakdown) ═══ -->
              <el-collapse class="mt-2" v-if="patch.score_breakdown">
                <el-collapse-item title="📊 多维分数明细 (Score Breakdown)">
                  <div class="score-breakdown">
                    <div class="score-row" v-if="patch.score_breakdown.embedding_score !== undefined">
                      <span class="score-label">Embedding 向量相似度</span>
                      <el-progress
                        :percentage="Math.round(patch.score_breakdown.embedding_score * 100)"
                        :stroke-width="8" :color="scoreColor(patch.score_breakdown.embedding_score)"
                        style="flex: 1; margin: 0 12px;"
                      />
                      <span class="score-pct">{{ (patch.score_breakdown.embedding_score * 100).toFixed(0) }}%</span>
                    </div>
                    <div class="score-row" v-if="patch.score_breakdown.reranker_score !== undefined">
                      <span class="score-label">Reranker 语义重排</span>
                      <el-progress
                        :percentage="Math.round(patch.score_breakdown.reranker_score * 100)"
                        :stroke-width="8" :color="scoreColor(patch.score_breakdown.reranker_score)"
                        style="flex: 1; margin: 0 12px;"
                      />
                      <span class="score-pct">{{ (patch.score_breakdown.reranker_score * 100).toFixed(0) }}%</span>
                    </div>
                    <div class="score-row" v-if="patch.score_breakdown.expert_rule_score !== undefined">
                      <span class="score-label">专家规则匹配</span>
                      <el-progress
                        :percentage="Math.round(patch.score_breakdown.expert_rule_score * 100)"
                        :stroke-width="8" :color="scoreColor(patch.score_breakdown.expert_rule_score)"
                        style="flex: 1; margin: 0 12px;"
                      />
                      <span class="score-pct">{{ (patch.score_breakdown.expert_rule_score * 100).toFixed(0) }}%</span>
                    </div>
                    <div class="score-row" v-if="patch.score_breakdown.callstack_match_score !== undefined">
                      <span class="score-label">调用栈匹配</span>
                      <el-progress
                        :percentage="Math.round(patch.score_breakdown.callstack_match_score * 100)"
                        :stroke-width="8" :color="scoreColor(patch.score_breakdown.callstack_match_score)"
                        style="flex: 1; margin: 0 12px;"
                      />
                      <span class="score-pct">{{ (patch.score_breakdown.callstack_match_score * 100).toFixed(0) }}%</span>
                    </div>
                    <div class="score-row" v-if="patch.score_breakdown.subsystem_match_score !== undefined">
                      <span class="score-label">子系统匹配</span>
                      <el-progress
                        :percentage="Math.round(patch.score_breakdown.subsystem_match_score * 100)"
                        :stroke-width="8" :color="scoreColor(patch.score_breakdown.subsystem_match_score)"
                        style="flex: 1; margin: 0 12px;"
                      />
                      <span class="score-pct">{{ (patch.score_breakdown.subsystem_match_score * 100).toFixed(0) }}%</span>
                    </div>
                    <div class="score-row" v-if="patch.score_breakdown.version_match_score !== undefined">
                      <span class="score-label">版本匹配</span>
                      <el-progress
                        :percentage="Math.round(patch.score_breakdown.version_match_score * 100)"
                        :stroke-width="8" :color="scoreColor(patch.score_breakdown.version_match_score)"
                        style="flex: 1; margin: 0 12px;"
                      />
                      <span class="score-pct">{{ (patch.score_breakdown.version_match_score * 100).toFixed(0) }}%</span>
                    </div>
                    <div class="score-row" v-if="patch.score_breakdown.llm_judge_score !== undefined">
                      <span class="score-label">LLM Judge 因果评分</span>
                      <el-progress
                        :percentage="Math.round(patch.score_breakdown.llm_judge_score * 100)"
                        :stroke-width="8" :color="'#7c4dff'"
                        style="flex: 1; margin: 0 12px;"
                      />
                      <span class="score-pct">{{ (patch.score_breakdown.llm_judge_score * 100).toFixed(0) }}%</span>
                    </div>

                    <!-- ★ 维度贡献明细 (Score Contribution) -->
                    <template v-if="patch.score_breakdown.score_contribution">
                      <el-divider />
                      <div class="score-contribution-header">
                        <span>💡 各维度贡献明细 (Weight × Score)</span>
                        <el-tag size="small" type="warning" effect="plain">为什么是这个分数？</el-tag>
                      </div>
                      <div class="contribution-table">
                        <div class="contrib-row" v-if="patch.score_breakdown.score_contribution.embedding">
                          <span class="contrib-label">Embedding</span>
                          <span class="contrib-formula">{{ patch.score_breakdown.fusion_weights?.embedding?.toFixed(2) || '0.15' }} × {{ patch.score_breakdown.embedding_score?.toFixed(2) }}</span>
                          <span class="contrib-value">= {{ patch.score_breakdown.score_contribution.embedding?.toFixed(3) }}</span>
                        </div>
                        <div class="contrib-row" v-if="patch.score_breakdown.score_contribution.reranker">
                          <span class="contrib-label">Reranker</span>
                          <span class="contrib-formula">{{ patch.score_breakdown.fusion_weights?.reranker?.toFixed(2) || '0.25' }} × {{ patch.score_breakdown.reranker_score?.toFixed(2) }}</span>
                          <span class="contrib-value">= {{ patch.score_breakdown.score_contribution.reranker?.toFixed(3) }}</span>
                        </div>
                        <div class="contrib-row" v-if="patch.score_breakdown.score_contribution.expert_rule">
                          <span class="contrib-label">Expert Rule</span>
                          <span class="contrib-formula">{{ patch.score_breakdown.fusion_weights?.expert_rule?.toFixed(2) || '0.15' }} × {{ patch.score_breakdown.expert_rule_score?.toFixed(2) }}</span>
                          <span class="contrib-value">= {{ patch.score_breakdown.score_contribution.expert_rule?.toFixed(3) }}</span>
                        </div>
                        <div class="contrib-row" v-if="patch.score_breakdown.score_contribution.callstack_match">
                          <span class="contrib-label">Call Stack</span>
                          <span class="contrib-formula">{{ patch.score_breakdown.fusion_weights?.callstack_match?.toFixed(2) || '0.10' }} × {{ patch.score_breakdown.callstack_match_score?.toFixed(2) }}</span>
                          <span class="contrib-value">= {{ patch.score_breakdown.score_contribution.callstack_match?.toFixed(3) }}</span>
                        </div>
                        <div class="contrib-row" v-if="patch.score_breakdown.score_contribution.subsystem_match">
                          <span class="contrib-label">Subsystem</span>
                          <span class="contrib-formula">{{ patch.score_breakdown.fusion_weights?.subsystem_match?.toFixed(2) || '0.10' }} × {{ patch.score_breakdown.subsystem_match_score?.toFixed(2) }}</span>
                          <span class="contrib-value">= {{ patch.score_breakdown.score_contribution.subsystem_match?.toFixed(3) }}</span>
                        </div>
                        <div class="contrib-row" v-if="patch.score_breakdown.score_contribution.version_match">
                          <span class="contrib-label">Version</span>
                          <span class="contrib-formula">{{ patch.score_breakdown.fusion_weights?.version_match?.toFixed(2) || '0.10' }} × {{ patch.score_breakdown.version_match_score?.toFixed(2) }}</span>
                          <span class="contrib-value">= {{ patch.score_breakdown.score_contribution.version_match?.toFixed(3) }}</span>
                          <span v-if="patch.score_breakdown.version_penalty" class="version-penalty-badge" :class="patch.score_breakdown.version_penalty < 0 ? 'penalty' : 'bonus'">
                            {{ patch.score_breakdown.version_penalty < 0 ? '▼' : '▲' }}{{ Math.abs(patch.score_breakdown.version_penalty).toFixed(3) }}
                          </span>
                        </div>
                        <div class="contrib-row total-row">
                          <span class="contrib-label" style="font-weight: 700;">Total</span>
                          <span class="contrib-formula">—</span>
                          <span class="contrib-value" style="font-weight: 700;">= {{ patch.score_breakdown.final_score?.toFixed(3) }}</span>
                        </div>
                      </div>
                    </template>
                  </div>
                </el-collapse-item>
              </el-collapse>

              <!-- ═══ Zone 3.6: 版本感知分析 (Version Analysis) ═══ -->
              <div class="version-analysis mt-2" v-if="patch.version_analysis?.crash_kernel_version || patch.version_analysis?.patch_kernel_version">
                <el-divider />
                <div class="version-header">
                  <span>📊 版本分析 (Version-aware)</span>
                </div>
                <div class="version-grid">
                  <div class="version-item" v-if="patch.version_analysis.crash_kernel_version">
                    <span class="version-label">Crash Kernel:</span>
                    <el-tag size="small" type="danger">{{ patch.version_analysis.crash_kernel_version }}</el-tag>
                  </div>
                  <div class="version-item" v-if="patch.version_analysis.patch_kernel_version">
                    <span class="version-label">Patch Kernel:</span>
                    <el-tag size="small" type="success">{{ patch.version_analysis.patch_kernel_version }}</el-tag>
                  </div>
                  <div class="version-item" v-if="patch.version_analysis.version_distance">
                    <span class="version-label">版本距离:</span>
                    <span class="version-value">{{ patch.version_analysis.version_distance }}</span>
                  </div>
                  <div class="version-item" v-if="patch.version_analysis.compatibility">
                    <span class="version-label">版本兼容:</span>
                    <el-tag
                      size="small"
                      :type="compatibilityTagType(patch.version_analysis.compatibility)"
                    >
                      {{ patch.version_analysis.compatibility }}
                    </el-tag>
                  </div>
                </div>
                <p class="text-sm text-muted mt-2" v-if="patch.version_analysis.compatibility_reason">
                  {{ patch.version_analysis.compatibility_reason }}
                </p>
              </div>

              <!-- ═══ Zone 4: Commit Message (默认展开3行) ═══ -->
              <div class="commit-message-block mt-3" v-if="patch.commit.message">
                <div class="message-preview" :class="{ expanded: patch._msgExpanded }">
                  {{ patch._msgExpanded ? patch.commit.message : (patch.commit.message?.slice(0, 200) || '') }}
                </div>
                <el-button
                  v-if="(patch.commit.message?.length || 0) > 200"
                  text size="small" type="primary"
                  @click="patch._msgExpanded = !patch._msgExpanded"
                >
                  {{ patch._msgExpanded ? '[收起]' : '[展开更多]' }}
                </el-button>
              </div>

              <!-- ═══ Zone 5: Diff 预览 ═══ -->
              <el-collapse class="mt-2">
                <el-collapse-item title="查看 Diff 预览">
                  <pre class="diff-preview"><code>{{ patch.commit.diff_preview || '(原始 diff 未存入索引)' }}</code></pre>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>

          <el-empty v-if="!currentTask.result.matched_patches?.length" description="未找到匹配的补丁" />
        </el-card>

        <!-- ★ 结果底部操作按钮 -->
        <div class="result-actions mt-4" style="text-align: center; padding: 20px 0;">
          <el-button type="primary" size="large" :icon="Plus" @click="resetForm">
            开始新分析
          </el-button>
          <el-button size="large" @click="$router.push('/history')" :icon="Clock">
            查看历史记录
          </el-button>
        </div>

        <!-- 🔎 检索策略与查询文本 -->
        <el-collapse class="mt-4" v-if="currentTask.result.retrieval_query">
          <el-collapse-item title="🔎 检索策略与查询文本">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="检索模式">
                <el-tag size="small" type="primary">{{ currentTask.result.retrieval_mode || 'standard' }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="检索流水线">
                Phase 1: Recall (Top-100) → Phase 2: Rule Filter → Phase 3: BGE-Reranker-v2 → Phase 4: LLM Judge
              </el-descriptions-item>
              <el-descriptions-item label="向量查询文本">
                <pre style="margin: 0; font-size: 11px; max-height: 200px; overflow-y: auto; background: #f5f5f5; padding: 8px; border-radius: 4px;">{{ currentTask.result.retrieval_query }}</pre>
              </el-descriptions-item>
            </el-descriptions>
          </el-collapse-item>
        </el-collapse>

        <!-- ★ 数据源提示 -->
        <el-alert
          v-if="currentTask.result?.analysis_mode === 'data'"
          title="📦 当前使用 Demo 数据集 (data)，召回范围有限。建议下载全量数据集以获得更准确的结果。"
          type="info"
          :closable="true"
          show-icon
          class="mt-4"
        />

        <!-- ★ Evidence Coverage — 证据完整度评估 (比赛加分模块) -->
        <el-card shadow="hover" class="section-card mt-4" v-if="currentTask.result.evidence_coverage">
          <template #header>
            <div class="section-header">
              <span>📋 证据完整度评估 (Evidence Coverage)</span>
              <el-tag
                :type="coverageReliabilityTag(currentTask.result.evidence_coverage.reliability)"
                size="large"
              >
                {{ currentTask.result.evidence_coverage.reliability }}
              </el-tag>
            </div>
          </template>
          <el-progress
            :percentage="currentTask.result.evidence_coverage.coverage_pct"
            :stroke-width="12"
            :color="coverageColor(currentTask.result.evidence_coverage.coverage_pct)"
            style="margin-bottom: 16px;"
          >
            <template #default="{ percentage }">
              <span style="font-weight: 700; font-size: 14px;">{{ percentage }}%</span>
            </template>
          </el-progress>
          <p class="text-sm text-muted mb-3">{{ currentTask.result.evidence_coverage.reliability_reason }}</p>
          <el-table
            :data="currentTask.result.evidence_coverage.items"
            size="small"
            stripe
            style="width: 100%;"
          >
            <el-table-column prop="name" label="Evidence Item" width="160" />
            <el-table-column prop="weight" label="Weight" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="row.weight === 'High' ? 'danger' : row.weight === 'Medium' ? 'warning' : 'info'" size="small">
                  {{ row.weight }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="Status" width="100" align="center">
              <template #default="{ row }">
                <el-icon v-if="row.status === 'available'" color="#4caf50"><CircleCheck /></el-icon>
                <el-icon v-else-if="row.status === 'partial'" color="#ff9800"><WarningFilled /></el-icon>
                <el-icon v-else color="#f44336"><CircleClose /></el-icon>
                <span style="margin-left: 4px; font-size: 12px;">{{ row.status === 'available' ? '✓' : row.status === 'partial' ? '~' : '✗' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="used" label="Used" width="70" align="center">
              <template #default="{ row }">
                <el-tag :type="row.used ? 'success' : 'info'" size="small">{{ row.used ? 'Yes' : 'No' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="detail" label="Detail" min-width="200" show-overflow-tooltip />
          </el-table>
        </el-card>

        <!-- LLM 分析报告 -->
        <el-card shadow="hover" class="section-card mt-4" v-if="currentTask.result.llm_explanation">
          <template #header>
            <div class="section-header">
              <span>🤖 LLM Analysis Report</span>
              <el-tag size="small" type="info">Evidence-Aware</el-tag>
            </div>
          </template>
          <div class="llm-explanation" v-html="renderedExplanation"></div>
        </el-card>

        <!-- ═══ Ranking Strategy 排序策略说明 ═══ -->
        <el-card shadow="hover" class="section-card mt-4" v-if="currentTask.result.matched_patches?.length">
          <template #header>
            <span>📊 Ranking Strategy</span>
          </template>
          <div class="ranking-strategy">
            <p class="text-sm text-muted mb-2">Final Score = Expert Rule + Embedding Similarity + Cross Encoder Rerank</p>
            <div class="strategy-items">
              <div class="strategy-item">
                <el-tag size="small" type="primary">Expert Rule</el-tag>
                <span class="text-sm ml-2">Subsystem match + Bug Type match (28 expert rules)</span>
              </div>
              <div class="strategy-item mt-2">
                <el-tag size="small" type="success">Embedding Similarity</el-tag>
                <span class="text-sm ml-2">BGE-M3 semantic vector retrieval (1024-dim)</span>
              </div>
              <div class="strategy-item mt-2">
                <el-tag size="small" type="warning">Cross Encoder Rerank</el-tag>
                <span class="text-sm ml-2">BGE-Reranker-v2 cross-encoder re-ranking</span>
              </div>
              <div class="strategy-item mt-2" v-if="currentTask.result.root_cause?.kernel_version">
                <el-tag size="small" type="danger">Version Match</el-tag>
                <span class="text-sm ml-2">Kernel version filtering + weighting</span>
              </div>
            </div>
          </div>
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
            <el-button @click="resetForm">新建分析</el-button>
          </template>
        </el-result>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAnalysisStore } from '@/stores/analysis'
import {
  bugTypeLabel, shortHash, formatPercent, formatScore, scoreInterpretation, copyToClipboard,
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
  // ★ 显式重置 reactive 表单数据（必须在 currentTaskId 清空之前）
  // 原因：表单被 v-if 销毁后 formRef 为 null，resetFields() 无法执行；
  //       且 el-form 的 resetFields 重置到"挂载时快照"而非代码默认值
  form.log_content = ''
  form.log_type = 'dmesg'
  form.kernel_version = ''
  form.top_k = 5
  form.enable_llm_explanation = true
  form.llm_mode = 'free'
  form.user_api_key = ''
  form.user_api_base = ''
  form.user_api_model = ''

  // 清空任务状态（触发 showResult=false，表单重新渲染）
  analysisStore.currentTaskId = null

  // 清除 URL 参数（防止刷新后恢复旧任务）
  router.replace('/analyze')

  // 等待表单重新挂载后清除验证状态
  nextTick(() => {
    formRef.value?.resetFields()
  })
}

function retryAnalysis() {
  resetForm()
}

function copyText(text) {
  copyToClipboard(text)
  ElMessage.success('已复制到剪贴板')
}

function rankColor(rank) {
  const colors = ['#1976D2', '#4caf50', '#ff9800', '#7c4dff', '#ff6d00']
  return colors[rank - 1] || '#78909c'
}

/**
 * 根据分数返回进度条颜色
 * @param {number} score - 0.0 ~ 1.0
 * @returns {string} 颜色 hex 值
 */
function scoreColor(score) {
  if (score >= 0.85) return '#4caf50'
  if (score >= 0.70) return '#8bc34a'
  if (score >= 0.55) return '#ff9800'
  if (score >= 0.40) return '#ff5722'
  return '#f44336'
}

/**
 * 版本兼容性对应的 Element Plus Tag 类型
 */
function compatibilityTagType(compatibility) {
  const map = { 'High': 'success', 'Medium': 'warning', 'Low': 'danger', 'Unknown': 'info' }
  return map[compatibility] || 'info'
}

/**
 * 证据完整度可靠性评级对应的 Tag 类型
 */
function coverageReliabilityTag(reliability) {
  const map = { 'High': 'success', 'Medium': 'warning', 'Low': 'danger' }
  return map[reliability] || 'info'
}

/**
 * 证据完整度百分比对应的进度条颜色
 */
function coverageColor(pct) {
  if (pct >= 70) return '#4caf50'
  if (pct >= 40) return '#ff9800'
  return '#f44336'
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
  } else if (!taskId) {
    // ★ 防护：URL 无 task 参数时强制回到输入模式
    // 防止 store 持久化恢复的陈旧 currentTaskId 导致表单不显示
    analysisStore.currentTaskId = null
  }
})

watch(() => route.query.task, (taskId) => {
  if (taskId && analysisStore.tasks[taskId]) {
    analysisStore.setCurrentTask(taskId)
    if (analysisStore.tasks[taskId].status === 'running') {
      analysisStore.startPolling(taskId)
    }
  } else if (!taskId) {
    // ★ URL 中 task 参数被清除后，自动回到输入模式
    analysisStore.currentTaskId = null
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

/* ── 紧凑输入栏 (有结果时显示) ──────────────── */
.compact-input-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
  gap: 16px;
}
.compact-input-hint {
  font-size: 14px;
  color: var(--color-text-muted);
  flex: 1;
}

/* ── 结果操作栏 ────────────────────────────────── */
.result-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

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

/* ── Matching Evidence ────────────────────────── */
.matching-evidence {
  background: rgba(76, 175, 80, 0.06);
  border: 1px solid rgba(76, 175, 80, 0.15);
  border-radius: 8px;
  padding: 12px 16px;
}
.evidence-title {
  font-size: 13px;
  font-weight: 600;
  color: #2e7d32;
  margin-bottom: 8px;
}
.evidence-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
}
.evidence-item {
  font-size: 12px;
  color: var(--color-text);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.evidence-check {
  color: #4caf50;
  font-weight: 700;
}

/* ── Matching Score ───────────────────────────── */
.matching-score {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.score-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 16px;
  background: rgba(25, 118, 210, 0.06);
  border-radius: 8px;
  min-width: 120px;
}
.score-item.final-score {
  background: rgba(25, 118, 210, 0.12);
  border: 1px solid rgba(25, 118, 210, 0.25);
}
.score-label {
  font-size: 11px;
  color: var(--color-text-muted, #78909c);
  margin-bottom: 2px;
}
.score-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-primary, #1976D2);
}

/* ── Commit Message Block ─────────────────────── */
.commit-message-block {
  border-left: 3px solid var(--color-border, #e0e0e0);
  padding-left: 12px;
}
.message-preview {
  font-size: 13px;
  color: var(--color-text-muted, #78909c);
  line-height: 1.6;
  max-height: 4.8em;
  overflow: hidden;
  transition: max-height 0.3s;
}
.message-preview.expanded {
  max-height: none;
}

/* ── Ranking Strategy ─────────────────────────── */
.strategy-items {
  padding: 8px 0;
}
.strategy-item {
  display: flex;
  align-items: center;
}

/* ── Root Cause Evidence ──────────────────────── */
.evidence-section {
  background: rgba(25, 118, 210, 0.03);
  border: 1px solid rgba(25, 118, 210, 0.10);
  border-radius: 8px;
  padding: 14px 16px;
}
.evidence-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-primary-dark, #1565C0);
  margin-bottom: 12px;
}
.evidence-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.evidence-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.evidence-label {
  font-weight: 500;
  color: var(--color-text-muted, #78909c);
  min-width: 110px;
}
.evidence-value {
  color: var(--color-text);
}
.evidence-code {
  background: #f0f4f8;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  font-family: monospace;
  color: #e53935;
}

/* ── Why-Not Alert ────────────────────────────── */
.why-not-alert {
  background: rgba(255, 152, 0, 0.04) !important;
  border-color: rgba(255, 152, 0, 0.15) !important;
}
.why-not-list {
  margin: 4px 0;
  padding-left: 18px;
}
.why-not-list li {
  font-size: 12px;
  line-height: 1.7;
}
.why-not-list.same li { color: #2e7d32; }
.why-not-list.different li { color: #c62828; }

/* ── Score Breakdown ──────────────────────────── */
.score-breakdown {
  padding: 8px 0;
}
.score-row {
  display: flex;
  align-items: center;
  padding: 6px 0;
}
.score-row .score-label {
  width: 140px;
  font-size: 12px;
  color: var(--color-text-muted, #78909c);
  flex-shrink: 0;
}
.score-pct {
  width: 40px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  text-align: right;
  flex-shrink: 0;
}

/* ── Version Analysis ─────────────────────────── */
.version-analysis {
  background: rgba(76, 175, 80, 0.03);
  border: 1px solid rgba(76, 175, 80, 0.10);
  border-radius: 8px;
  padding: 12px 16px;
}
.version-header {
  font-size: 13px;
  font-weight: 600;
  color: #2e7d32;
  margin-bottom: 10px;
}
.version-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
}
.version-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.version-label {
  font-weight: 500;
  color: var(--color-text-muted, #78909c);
}
.version-value {
  color: var(--color-text);
  font-weight: 500;
}

/* ── Result Actions ──────────────────────────── */
.result-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
}

/* ── Possible Causes ─────────────────────────── */
.possible-causes-section {
  background: rgba(245, 124, 0, 0.04);
  border: 1px solid rgba(245, 124, 0, 0.12);
  border-radius: 8px;
  padding: 14px 16px;
}
.possible-causes-list {
  margin: 8px 0 0;
  padding-left: 20px;
}
.possible-causes-list li {
  font-size: 13px;
  line-height: 1.8;
  color: var(--color-text);
}

/* ── Confidence Breakdown ────────────────────── */
.confidence-breakdown-section {
  background: rgba(25, 118, 210, 0.03);
  border: 1px solid rgba(25, 118, 210, 0.10);
  border-radius: 8px;
  padding: 14px 16px;
}
.confidence-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}
.confidence-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.confidence-item.total {
  border-top: 1px dashed var(--color-border);
  padding-top: 8px;
  margin-top: 4px;
}
.conf-label {
  width: 130px;
  font-size: 12px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}
.conf-pct {
  width: 55px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  text-align: right;
  flex-shrink: 0;
}

/* ── Score Contribution Table ────────────────── */
.score-contribution-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary-dark);
  margin-bottom: 8px;
}
.contribution-table {
  background: rgba(0, 0, 0, 0.02);
  border-radius: 6px;
  padding: 8px 12px;
}
.contrib-row {
  display: flex;
  align-items: center;
  padding: 4px 0;
  gap: 8px;
  font-size: 12px;
}
.contrib-row.total-row {
  border-top: 1px dashed var(--color-border);
  margin-top: 4px;
  padding-top: 6px;
}
.contrib-label {
  width: 90px;
  flex-shrink: 0;
  color: var(--color-text-muted);
}
.contrib-formula {
  flex: 1;
  color: var(--color-text-muted);
  font-family: monospace;
}
.contrib-value {
  width: 70px;
  text-align: right;
  flex-shrink: 0;
  color: var(--color-primary);
  font-family: monospace;
}
.version-penalty-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: monospace;
}
.version-penalty-badge.penalty {
  background: rgba(244, 67, 54, 0.12);
  color: #c62828;
}
.version-penalty-badge.bonus {
  background: rgba(76, 175, 80, 0.12);
  color: #2e7d32;
}
</style>
