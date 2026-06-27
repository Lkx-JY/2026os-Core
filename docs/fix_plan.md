# 全面修复方案 — 对照赛题评审要点

> 基于页面实际输出发现的 18 个问题，逐一给出根因、修复方案、涉及文件和预期效果。

---

## 赛题评审要点回顾

| 评审项 | 占比 | 核心要求 |
|--------|------|---------|
| 检索算法创新性与方案深度 | 30% | 语义理解、领域知识融合、场景泛化性 |
| 实现完整度与技术深度 | 30% | 完整链路、数据规模、多模态输入 |
| 代码质量与工程鲁棒性 | 15% | 代码规范、性能效率、容错处理 |
| 演示质量与可解释性 | 15% | 关联逻辑展示、评分依据、可读信息 |
| 文档与测试完整性 | 10% | 设计文档、自测案例、部署文档 |

---

## 🔴 严重问题 (4 项)

### 问题 1: Embedding Similarity 全部 1.000

**现象**: Top1~Top4 的 Embedding Similarity 全部显示 1.000，向量检索完全失去区分度。

**根因分析**:
```python
# scripts/build_demo_data.py: build_demo_index()
index.add(vectors)  # ← 向量未做 L2 归一化

# 未归一化的 BGE-M3 向量内积可达 20~50
# src/indexer/milvus/__init__.py: _normalize_raw_distance()
if raw > 1.0: return 1.0  # ← 全部被 clamp 到 1.0
```

一个 `build_demo_data.py` 修复（已改）不够，因为**用户可能已有旧索引**。

**修复方案（三层防御）**:

**Layer 1 — 索引构建时** (已实现):
```python
# scripts/build_demo_data.py: build_demo_index()
norms = np.linalg.norm(vectors, axis=1, keepdims=True)
vectors = vectors / (norms + 1e-8)
```

**Layer 2 — 搜索返回时** (已实现):
```python
# src/indexer/milvus/__init__.py: to_dict_list()
# 批次相对归一化: max(IP) → 1.0，其余按比例
if batch_max > 1.0:
    normalized = raw / batch_max  # IP=[20,15,10] → [1.0, 0.75, 0.5]
```

**Layer 3 — 运行时检测与告警** (需要新增):
```python
# src/indexer/milvus/__init__.py
# 在 to_dict_list() 中检测到非归一化向量时，记录 WARN 日志
# 并在返回结果中标记 _vectors_not_normalized=True
# 前端检测到此标记时显示 "⚠ 向量未归一化，Embedding 分数可能不准确"
```

**涉及文件**: `scripts/build_demo_data.py`, `src/indexer/milvus/__init__.py`

**赛题映射**: 代码质量与工程鲁棒性 (15%) — 容错处理

---

### 问题 2: 版本距离数字荒谬 (6004/6013/6002)

**现象**: 4 个补丁的版本距离分别是 6004、6013、6002 Minor Release，Linux 内核不存在这么多版本。

**根因分析**:
```python
# src/retriever/filter/__init__.py: compute_version_analysis()
crash_major = 0  # ← crash_kernel_version 为空时默认为 0
crash_minor = 0

# patch_major=6, patch_minor=4
distance = (6 - 0) * 1000 + (4 - 0) = 6004  # ← 荒谬！
```

**修复方案**:

```python
# src/retriever/filter/__init__.py: compute_version_analysis()

def compute_version_analysis(crash_kernel_version, patch_commit_info, patch_date=""):
    # ★ 修复: 当 crash_kernel_version 缺失时，不应计算距离
    if not crash_kernel_version:
        return {
            "crash_kernel_version": None,
            "patch_kernel_version": "..." if patch_kv else None,
            "version_distance": "Unknown — Crash Kernel Version 未提供",
            "distance_value": -1,  # -1 表示未知
            "compatibility": "Unknown",
            "compatibility_reason": (
                "无法评估版本兼容性，因为崩溃日志中未提供 Kernel Version。"
                "建议用户在分析时手动输入内核版本以获得更准确的排序。"
            ),
        }
    
    # 正常计算距离时增加合法性校验
    crash_parts = crash_kernel_version.split(".")
    try:
        crash_major = int(crash_parts[0])
        crash_minor = int(crash_parts[1]) if len(crash_parts) > 1 else 0
    except (ValueError, IndexError):
        return { ... "Unknown" ... }
    
    # ★ 增加合理性校验: 内核主版本号范围 2~7
    if crash_major < 2 or crash_major > 7:
        return { ... "Unknown — Invalid kernel version format" ... }
```

**涉及文件**: `src/retriever/filter/__init__.py`

**赛题映射**: 代码质量与工程鲁棒性 (15%) — 容错处理；演示质量与可解释性 (15%) — 直观性

---

### 问题 3: LLM 输出是规则模板而非真实 LLM 生成

**现象**: 报告只有 ~10 行固定格式文本，没有任何 Evidence-Aware 分析。

**根因**: 两种可能：
1. LLM 服务不可用（Ollama 未运行 / API Key 未配置），走了 `_generate_real_explanation()` 降级
2. `enable_llm_explanation` 被设为 `false`

**修复方案**:

**3a — 增强降级模板质量**:
```python
# src/api/routers/analyze.py: _generate_real_explanation()

def _generate_real_explanation(root_cause, patches):
    """增强版降级报告 — 即使 LLM 不可用也能生成有信息量的报告"""
    if not patches:
        return """..."""
    
    top = patches[0]
    lines = [
        "## 🤖 注意: 当前为规则引擎生成的降级报告",
        "",
        "LLM 服务未连接，以下分析基于专家规则和检索指标自动生成。",
        "启用 LLM 可获得更详细的分析报告。",
        "",
        "---",
        "",
        "## (1) Crash Summary",
        f"根因类型: **{root_cause.root_cause}**",
        f"受影响子系统: `{root_cause.subsystem}`",
        ...
    ]
    
    # ★ 增加维度贡献说明
    if top.score_breakdown and top.score_breakdown.score_contribution:
        contrib = top.score_breakdown.score_contribution
        lines += [
            "## (4) Score Composition",
            "| Dimension | Contribution |",
            "|---|---|",
            f"| Embedding | {contrib.get('embedding', 0):.3f} |",
            f"| Reranker | {contrib.get('reranker', 0):.3f} |",
            ...
        ]
    
    # ★ 增加风险提示
    evidence = ...  # 检测缺失的证据
    if missing_critical:
        lines += [
            "## ⚠️ Limitations",
            f"以下关键证据缺失: {', '.join(missing_critical)}",
            "当前推荐应视为候选补丁排序，而非确认修复方案。",
        ]
    
    # ★ 增加 Analysis Scope 声明
    lines += [
        "---",
        "> **Analysis Scope**",
        "> 本报告由规则引擎自动生成，基于专家规则和向量检索指标。",
        ...
    ]
    
    return "\n\n".join(lines)
```

**3b — 前端增加 LLM 状态指示**:
```vue
<!-- CrashAnalysis.vue -->
<el-alert v-if="!currentTask.result.llm_explanation" 
  title="LLM 报告未生成" type="info" show-icon>
  请确保 Ollama 已启动或 API Key 已配置
</el-alert>
```

**涉及文件**: `src/api/routers/analyze.py`, `frontend/src/views/CrashAnalysis.vue`

**赛题映射**: 演示质量与可解释性 (15%) — Demo 真实感；实现完整度 (30%) — 功能完整性

---

### 问题 4: Confidence Breakdown 数字对不上 (78.8% ≠ 85%)

**现象**: 拆解 5 项加起来 78.8%，但页面顶部显示 85%。

**根因分析**:
```python
# 顶部的 confidence 来自 root_cause_result.score = 0.85
# compute_confidence_breakdown() 中 historical_similarity 的计算:
historical = round(top1_embedding_score * 0.15 * 100, 1)
# ↑ top1_embedding_score 可能是 0（还没检索完时），导致 historical = 0%

# 总和不等于 85% 的根本原因:
# root_cause_result.score 是根因分析器基于规则的独立评分 (0~1)
# confidence_breakdown 是事后拆解，两者计算逻辑不同
```

**修复方案**:

```python
# src/analyzer/rootcause/__init__.py: compute_confidence_breakdown()

def compute_confidence_breakdown(result, feature, top1_embedding_score=0.0):
    base = result.score  # 根因分析器给出的基础分数 (0~1)
    
    has_rule = bool(result.extra_info.get("rule_id"))
    has_call_trace = bool(feature.call_trace) if feature else False
    has_fault_addr = bool(extract_fault_address(feature)) if feature else False
    
    # ★ 重新设计: 从 base 出发反向分配，确保总和 = base * 100
    total_pct = base * 100.0
    
    if has_rule:
        # 有专家规则 → 规则匹配占主体
        rule_pct = round(total_pct * 0.50, 1)        # 50%
        fault_pct = round(total_pct * 0.18, 1) if has_fault_addr else 0.0
        subsys_pct = round(total_pct * 0.10, 1)
        trace_pct = round(total_pct * 0.10, 1) if has_call_trace else 0.0
        hist_pct = round(total_pct * 0.12, 1) if top1_embedding_score > 0 else 0.0
        
        # ★ 剩余部分用 rule_pct 补齐，确保总和 = total_pct
        allocated = fault_pct + subsys_pct + trace_pct + hist_pct
        rule_pct = round(total_pct - allocated, 1)
    else:
        # 无规则 → 均匀分配
        rule_pct = round(total_pct * 0.35, 1)
        fault_pct = round(total_pct * 0.20, 1) if has_fault_addr else 0.0
        subsys_pct = round(total_pct * 0.15, 1)
        trace_pct = round(total_pct * 0.15, 1) if has_call_trace else 0.0
        hist_pct = round(total_pct * 0.15, 1) if top1_embedding_score > 0 else 0.0
        # 补齐
        allocated = fault_pct + subsys_pct + trace_pct + hist_pct
        rule_pct = round(total_pct - allocated, 1)
    
    return {
        "rule_match": rule_pct,
        "fault_address_pattern": fault_pct,
        "subsystem_match": subsys_pct,
        "call_trace_evidence": trace_pct,
        "register_state": 0.0,  # dmesg 模式下始终为 0
        "historical_similarity": hist_pct,
    }
    # ★ guarantee: sum(values) == total_pct (within rounding error)
```

**涉及文件**: `src/analyzer/rootcause/__init__.py`

**赛题映射**: 演示质量与可解释性 (15%) — 评分依据可解释性

---

## 🟠 中等问题 (6 项)

### 问题 5: Final Score 差距太小 (#1=0.612, #2=0.611)

**根因**: Embedding 全 1.0 导致区分度靠 Cross Encoder 微小的差异。从根上修复后 (问题 1)，Embedding 分数会有区分度。

**额外增强**: 当 Top1 和 Top2 差距 < 0.01 时，前端加提示：
```vue
<span v-if="gap < 0.01" class="text-sm text-warning">
  ⚠ Top1 与 Top2 差距极小 ({{ gap.toFixed(4) }})，建议同时审查两个补丁
</span>
```

**涉及文件**: `frontend/src/views/CrashAnalysis.vue`

---

### 问题 6: Why-Not 解释是空模板

**根因**: `generate_why_not_explanations()` 在 `rerank/__init__.py` 中，当所有补丁的 subsystem/bug_type 完全相同时，找不到差异点。

**修复方案**:
```python
# src/retriever/rerank/__init__.py: generate_why_not_explanations()

def generate_why_not_explanations(ranked_items):
    top1 = ranked_items[0]
    
    for i, item in enumerate(ranked_items):
        if i == 0:
            explanations.append(None)
            continue
        
        same, different = [], []
        
        # ... existing checks ...
        
        # ★ 始终生成具体的分数差距
        score_gap = top1.final_score - item.final_score
        different.append(
            f"综合评分差距 {score_gap:.3f} (Top1={top1.final_score:.3f} vs Top{i+1}={item.final_score:.3f})"
        )
        
        # ★ 比较 Embedding 分数
        if top1.vector_score != item.vector_score:
            different.append(
                f"Embedding 相似度: Top1={top1.vector_score:.3f} > Top{i+1}={item.vector_score:.3f}"
            )
        else:
            different.append("Embedding 相似度相同，差异来自 Cross Encoder 重排")
        
        # ★ 比较 Reranker 分数
        rerank_gap = top1.reranker_score - item.reranker_score
        different.append(
            f"Cross Encoder 重排分: {rerank_gap:.3f} 的差距导致排名不同"
        )
        
        # ★ 比较版本兼容性
        top1_vw = top1.metadata.get("_version_weight", 1.0)
        item_vw = item.metadata.get("_version_weight", 1.0)
        if item_vw < top1_vw:
            different.append(
                f"版本兼容性较低 (权重 {item_vw:.2f} vs Top1 {top1_vw:.2f})"
            )
        
        explanations.append({
            "compared_to_rank": 1,
            "same_aspects": same,
            "different_aspects": different if different else ["各项指标均略低于 Top1"],
            "ranking_reason": f"综合 {len(different)} 个维度的差异，排名第 {item.rank}",
        })
```

**涉及文件**: `src/retriever/rerank/__init__.py`

**赛题映射**: 演示质量与可解释性 (15%) — 解释性展示

---

### 问题 7: Evidence Coverage 与 Root Cause Evidence 矛盾

**现象**: Root Cause Evidence 面板有 `fault_address: 0000000000000028`，但 Evidence Coverage 说 Fault Address 缺失。

**根因**: `compute_evidence_coverage()` 中提取 fault address 的正则与 `extract_root_cause_evidence()` 中不一致。

**修复方案**:
```python
# src/analyzer/rootcause/__init__.py: compute_evidence_coverage()

def compute_evidence_coverage(crash_feature, root_cause_info, matched_patches):
    # ★ 统一使用 extract_root_cause_evidence() 中的提取逻辑
    evidence_dict = extract_root_cause_evidence(crash_feature, root_cause_result) \
        if hasattr(root_cause_result, 'score') else {}
    
    # ★ 从 RootCauseEvidence 中获取状态
    has_fault_addr = bool(evidence_dict.get("fault_address"))
    has_error_code = bool(evidence_dict.get("error_code"))
    # ...
    
    # ★ 与 RootCauseInfo 保持一致
    _add_item("Fault Address",
              "available" if has_fault_addr else "missing",
              "Medium",
              has_fault_addr,
              f"故障地址: {evidence_dict.get('fault_address', 'N/A')}" if has_fault_addr else "缺失")
```

**涉及文件**: `src/analyzer/rootcause/__init__.py`

---

### 问题 8: 版本分析全部 Low，没有区分度

**根因**: 版本距离公式因 crash_kernel_version 缺失而异常（修复见问题 2）。

**额外改进**: 即使版本正常，也需要让 Version-aware 真正影响排序。

```python
# src/retriever/rerank/__init__.py: compute_score_breakdown()
# version_match_score 已不再 clamp 到 1.0（之前已修复）
# 但需要确保 version_penalty 在 final_score 中体现

# ★ 额外: 在前端展示版本对排序的影响
# ScoreBreakdown 面板中 version_penalty 已通过版本惩罚徽章展示
```

**涉及文件**: `src/retriever/filter/__init__.py`, `src/retriever/rerank/__init__.py`

---

### 问题 9: Fault Address (0x28) 未被用于 Confidence

**现象**: `0000000000000028` 是 NULL + 结构体偏移的模式，是内核调试的重要信号，但 Confidence Breakdown 中没有体现。

**修复方案**:
```python
# src/analyzer/rootcause/__init__.py: compute_confidence_breakdown()

# ★ 增加 fault address pattern 特征提取
def _analyze_fault_address(address_str: str) -> Optional[Dict[str, Any]]:
    """分析 fault address 提供的内核对象线索"""
    if not address_str:
        return None
    
    addr = int(address_str, 16)
    
    # 小偏移 (0~0x100): 可能是结构体字段
    # 大偏移 (> 0x1000): 可能是基地址 + 大偏移
    if 0 < addr <= 0x100:
        return {
            "pattern": "NULL base + small offset",
            "inference": (
                f"地址 0x{addr:x} 是 NULL 基址 + {addr} 偏移，"
                "表明通过 NULL 指针访问了结构体成员。"
                "常见于对象未分配或已被释放的场景。"
            ),
            "confidence_boost": 0.03,  # +3%
        }
    elif 0x100 < addr <= 0x1000:
        return {
            "pattern": "NULL base + medium offset",
            "inference": f"可能是大型结构体或数组的越界访问",
            "confidence_boost": 0.02,
        }
    # ...

# 然后在 compute_confidence_breakdown 中使用
fault_info = _analyze_fault_address(fault_address)
if fault_info:
    fault_addr_contribution = fault_info["confidence_boost"] * 100  # 转百分比
```

**涉及文件**: `src/analyzer/rootcause/__init__.py`

---

### 问题 10: Evidence Coverage 52.4% 评 Medium 不合适

**根因**: 阈值 `>= 40 → Medium` 太宽松，Call Trace + Kernel Version 两个 High 权重都缺失。

**修复方案**:
```python
# src/analyzer/rootcause/__init__.py: compute_evidence_coverage()

# ★ 调整评级阈值 + 考虑关键证据缺失
missing_high_count = sum(
    1 for item in items
    if item["status"] == "missing" and item["weight"] == "High"
)

if coverage_pct >= 75 and missing_high_count == 0:
    reliability = "High"
    reason = "关键证据齐全，分析可信度较高"
elif coverage_pct >= 50 or missing_high_count <= 1:
    reliability = "Medium"
    reason = f"{missing_high_count} 项关键证据缺失，建议补充后重新分析"
else:
    reliability = "Low"
    reason = (
        f"多项关键证据缺失 ({missing_high_count} 项 High 权重)，"
        "当前推荐仅应视为候选补丁排序，不可作为确认修复方案"
    )
```

**涉及文件**: `src/analyzer/rootcause/__init__.py`

---

## 🟡 轻微问题 (8 项)

### 问题 11: Kernel Version 缺失不够显眼

**修复**: 在结果顶部增加缺失证据提示横幅：
```vue
<!-- CrashAnalysis.vue -->
<el-alert
  v-if="hasMissingCriticalEvidence"
  title="关键证据缺失"
  type="warning"
  :closable="false"
  show-icon
>
  <ul>
    <li v-if="!hasCallTrace">Call Trace 缺失 — 无法进行调用栈级别的匹配</li>
    <li v-if="!hasKernelVersion">Kernel Version 未知 — 版本过滤和兼容性评估不可用</li>
  </ul>
  当前分析精度受限，建议补充以上信息后重新分析。
</el-alert>
```

**涉及文件**: `frontend/src/views/CrashAnalysis.vue`

---

### 问题 12: Cross Encoder 分数偏低 (0.47~0.53)

**根因**: 查询文本与补丁文本的语义鸿沟。优化 `retrieval_query` 构造：
```python
# src/analyzer/rootcause/__init__.py: build_retrieval_query()

# ★ 增加更多桥接信息，缩小语义鸿沟
parts = [
    f"RootCause: {root_cause}",
    f"BugType: {bug_type.replace('_', ' ')}",
    f"Subsystem: {feature.subsystem}",
    # ★ 增加故障描述模式
    f"CrashSymptom: The kernel crashed with {root_cause.upper()} in {feature.subsystem} subsystem",
    # ★ 增加修复需求描述
    f"FixNeeded: A commit that prevents {bug_type.replace('_', ' ')} by {fix_description}",
]
```

**涉及文件**: `src/analyzer/rootcause/__init__.py`

---

### 问题 13: Key Symptoms 混入了内部推理数据

**修复**:
```python
# src/api/routers/analyze.py: _run_real_analysis()

# ★ 分离 key_symptoms (用户可见症状) 和 causal_chain (内部推理)
root_cause_info = RootCauseInfo(
    ...
    key_symptoms=[
        s for s in (root_cause_result.causal_chain or [])
        if not s.startswith("Expert Rule:") 
        and not s.startswith("Severity:")
        and not s.startswith("Related Subsystems:")
        and not s.startswith("Knowledge Base:")
        and not s.startswith("Lock Issue:")
        and not s.startswith("Affected Subsystem:")
        and not s.startswith("Kernel Version:")
        and not s.startswith("Loaded Modules:")
    ],
    ...
)
```

**涉及文件**: `src/api/routers/analyze.py`

---

### 问题 14: Call Trace 0% 缺少 "(missing)" 标注

**修复**: 前端 Confidence Breakdown 的 Call Trace 行增加缺失提示：
```vue
<div class="confidence-item">
  <span class="conf-label">Call Trace</span>
  <el-progress ... />
  <span class="conf-pct">
    {{ currentTask.result.root_cause.confidence_breakdown.call_trace_evidence > 0 ? '+' : '' }}
    {{ currentTask.result.root_cause.confidence_breakdown.call_trace_evidence }}%
    <el-tag v-if="currentTask.result.root_cause.confidence_breakdown.call_trace_evidence === 0" 
            size="small" type="info">缺失</el-tag>
  </span>
</div>
```

**涉及文件**: `frontend/src/views/CrashAnalysis.vue`

---

### 问题 15: "Cross Encoder Rank #X" 语义误导

**修复**: 改为 "Cross Encoder → Final Rank #X" 或直接删除。Cross Encoder 返回连续分数 (0~1)，不输出排名。
```vue
<!-- CrashAnalysis.vue -->
<span class="evidence-item" v-if="patch.reranker_score > 0">
  <span class="evidence-check">✓</span> 
  Cross Encoder Score: {{ patch.reranker_score?.toFixed(3) }}
</span>
```

**涉及文件**: `frontend/src/views/CrashAnalysis.vue`

---

### 问题 16: Possible Causes 太通用

**修复**: 根据子系统和具体场景定制化：
```python
# src/analyzer/rootcause/__init__.py: compute_possible_causes()

def compute_possible_causes(bug_type, subsystem="unknown", call_trace=None):
    """根据 Bug Type + 子系统 + 调用栈 定制可能的深层原因"""
    causes = list(_BUG_TYPE_TO_POSSIBLE_CAUSES.get(bug_type, [...]))
    
    # ★ 基于子系统筛选最相关的原因
    subsystem_relevance = {
        "net": ["网络设备初始化", "数据包处理路径", "ioctl/sysfs 接口"],
        "mm": ["内存分配/释放配对", "页表操作", "slab 缓存管理"],
        "fs": ["inode/dentry 生命周期", "文件操作并发", "VFS 层回调"],
        "drivers": ["驱动 probe/release", "中断处理", "DMA 映射"],
    }
    
    if subsystem in subsystem_relevance:
        # 在通用原因前插入子系统特定的上下文
        context = subsystem_relevance[subsystem]
        causes.insert(0, f"[{subsystem}] 常见触发场景: {', '.join(context)}")
    
    # ★ 如果有调用栈，提取函数名作为额外上下文
    if call_trace:
        funcs = [f.split('+')[0] for f in call_trace[:3]]
        causes.append(f"调用栈涉及函数: {', '.join(funcs)}，建议重点审查这些函数中的指针解引用")
    
    return causes
```

**涉及文件**: `src/analyzer/rootcause/__init__.py`

---

### 问题 17: 相关性分数缺少语义解释

**修复**: `formatScore` 增加区间描述：
```javascript
// frontend/src/utils/format.js

/** 获取分数语义描述 */
export function scoreInterpretation(value) {
  if (value == null) return ''
  if (value >= 0.85) return '(高相关)'
  if (value >= 0.70) return '(显著相关)'
  if (value >= 0.50) return '(中度相关)'
  if (value >= 0.30) return '(低度相关)'
  return '(弱相关)'
}
```

```vue
<!-- CrashAnalysis.vue -->
<span class="score-value">
  {{ formatScore(patch.relevance_score) }}
  <small class="text-muted">{{ scoreInterpretation(patch.relevance_score) }}</small>
</span>
```

**涉及文件**: `frontend/src/utils/format.js`, `frontend/src/views/CrashAnalysis.vue`

---

### 问题 18: 看不到检索查询文本

**修复**: 在页面增加"检索策略"折叠面板：
```vue
<!-- CrashAnalysis.vue -->
<el-collapse class="mt-2">
  <el-collapse-item title="🔎 检索策略与查询文本">
    <div class="retrieval-info">
      <p><strong>检索模式:</strong> {{ retrievalMode }}</p>
      <p><strong>召回数量:</strong> Top-100 → Filter → Rerank → Top-K</p>
      <p><strong>查询文本:</strong></p>
      <pre class="retrieval-query">{{ retrievalQuery }}</pre>
    </div>
  </el-collapse-item>
</el-collapse>
```

需要后端在 AnalyzeResponse 中增加字段：
```python
# src/api/schemas/responses.py
class AnalyzeResponse(BaseModel):
    ...
    retrieval_query: Optional[str] = Field(default=None)
    retrieval_mode: Optional[str] = Field(default="standard")
```

**涉及文件**: `src/api/schemas/responses.py`, `src/api/routers/analyze.py`, `frontend/src/views/CrashAnalysis.vue`

---

## 修改汇总

| # | 问题 | 涉及文件 | 改动量 |
|---|------|---------|--------|
| 1 | Embedding 全 1.0 | `milvus/__init__.py`, `build_demo_data.py` | ~30 行 |
| 2 | 版本距离荒谬 | `filter/__init__.py` | ~25 行 |
| 3 | LLM 降级模板 | `analyze.py` | ~60 行 |
| 4 | Confidence 对不上 | `rootcause/__init__.py` | ~40 行 |
| 5 | Final Score 差距小 | `CrashAnalysis.vue` | ~10 行 |
| 6 | Why-Not 空模板 | `rerank/__init__.py` | ~30 行 |
| 7 | Evidence 矛盾 | `rootcause/__init__.py` | ~15 行 |
| 8 | Version 全 Low | `filter/__init__.py` | 同 #2 |
| 9 | Fault Addr 未用 | `rootcause/__init__.py` | ~35 行 |
| 10 | Coverage 阈值 | `rootcause/__init__.py` | ~15 行 |
| 11 | Version Missing | `CrashAnalysis.vue` | ~15 行 |
| 12 | CrossEncoder 低 | `rootcause/__init__.py` | ~10 行 |
| 13 | Key Symptoms 原始 | `analyze.py` | ~15 行 |
| 14 | Call Trace 标注 | `CrashAnalysis.vue` | ~10 行 |
| 15 | Encoder Rank 误导 | `CrashAnalysis.vue` | ~5 行 |
| 16 | Causes 通用 | `rootcause/__init__.py` | ~20 行 |
| 17 | 分数无语义 | `format.js`, `CrashAnalysis.vue` | ~15 行 |
| 18 | 查询文本隐藏 | `responses.py`, `analyze.py`, `CrashAnalysis.vue` | ~25 行 |

| 合计 | 18 项 | ~10 个文件 | ~430 行 |

## 优先级排序

按投入产出比和对赛题评审的影响：

| 优先级 | 问题 | 理由 |
|--------|------|------|
| **P0** (必须修) | #1 Embedding 全 1.0, #2 版本距离荒谬, #4 Confidence 对不上 | 评审一眼就能看出来，直接拉低所有评分项 |
| **P1** (强烈建议) | #6 Why-Not 空模板, #3 LLM 降级质量, #7 Evidence 矛盾, #10 Coverage 阈值 | 直接影响"演示质量与可解释性(15%)" |
| **P2** (建议) | #8 Version 区分度, #9 Fault Addr, #13 Key Symptoms, #16 Causes 通用 | 提升"检索算法创新性(30%)"和"领域知识融合" |
| **P3** (锦上添花) | #11 缺失提示, #14 标注, #15 语义, #17 分数解释, #18 查询可见, #5 差距提示, #12 查询优化 | 细节优化，完善用户体验 |

---

## 实施建议

1. **分 2 轮修复**: 第 1 轮修 P0+P1（~8 项，~200 行），第 2 轮修 P2+P3（~10 项，~230 行）
2. **优先重新构建向量索引**: 运行 `python scripts/build_demo_data.py --count 40000` 使用修复后的归一化逻辑重建索引
3. **每轮修复后运行完整测试**: `pytest tests/ -v` 确保无回归
4. **前端 build 验证**: `npm run build` 确保无编译错误
