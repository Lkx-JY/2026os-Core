# Retriever — 在线检索核心模块

> **Four-Stage Retrieval Architecture: Recall → Filter → Rerank → LLM Judge**

负责从向量数据库中检索与宕机分析结果匹配的补丁，是整个系统"在线语义检索"的核心实现。

---

## 目录

1. [模块架构](#1-模块架构)
2. [四阶段检索架构](#2-四阶段检索架构)
3. [子模块说明](#3-子模块说明)
4. [数据流](#4-数据流)
5. [检索模式](#5-检索模式)
6. [使用指南](#6-使用指南)

---

## 1. 模块架构

```
src/retriever/
├── __init__.py            # 模块入口 — 统一导出所有公共 API
├── recall/__init__.py     # ★ Phase 1: 向量召回 — Milvus/FAISS Top-K
├── filter/__init__.py     # ★ Phase 2: 规则过滤 — 子系统/版本/关键词
├── rerank/__init__.py     # ★ Phase 3+4: 语义重排 + LLM Judge
│                          #   - BGE-Reranker-v2 交叉编码
│                          #   - LLM Judge 因果关联评分
├── pipeline/__init__.py   # ★ 检索流水线 — End-to-End 编排
└── README.md              # 本文档
```

### 四阶段检索架构总览

```
RootCauseResult.retrieval_query
        │
        ▼
┌───────────────────────────┐
│ Phase 1: Vector Recall    │  BGE-M3 编码 → Milvus/FAISS Top-K 召回
│ (recall)                  │  - 支持混合检索 (向量 + 标量过滤)
│                           │  - 自动降级 Milvus → FAISS
└───────────┬───────────────┘
            │ Top-100 candidates
            ▼
┌───────────────────────────┐
│ Phase 2: Rule Filter      │  子系统/版本/Bug类型 硬过滤
│ (filter)                  │  - 28 个子系统支持
│                           │  - 安全补丁加权
│                           │  - 去重
└───────────┬───────────────┘
            │ ~60-80 candidates
            ▼
┌───────────────────────────┐
│ Phase 3: BGE Rerank       │  BGE-Reranker-v2 交叉编码
│ (rerank)                  │  - Query-Document 交互语义
│                           │  - 捕获细粒度关联
└───────────┬───────────────┘
            │ Top-20 candidates
            ▼
┌───────────────────────────┐
│ Phase 4: LLM Judge        │  大模型因果关联评分 [可选, deep 模式]
│ (rerank)                  │  - 根因匹配判断
│                           │  - 修复意图推理
│                           │  - 子系统相关性验证
└───────────┬───────────────┘
            │ 按综合分数排序
            ▼
    RankedResult (Top-K patches)
```

---

## 2. 四阶段检索架构

### Phase 1: Vector Recall (向量召回)

**目标**: 从百万级向量中快速召回 Top-K 语义相关的候选 commit。

**实现**:
- 使用 BGE-M3 将 `retrieval_query` 编码为 1024 维向量
- Milvus IVF_FLAT / HNSW 索引实现快速近似搜索
- 支持标量过滤 (混合检索): `subsystem=="mm" && bug_type=="deadlock"`
- 自动降级: Milvus → FAISS

**性能**:
- Milvus: 100 万向量中召回 Top-100 < 10ms
- FAISS: 10 万向量中召回 Top-100 < 5ms

### Phase 2: Rule Filter (规则过滤)

**目标**: 基于确定性规则快速缩小候选范围。

**过滤维度**:
| 过滤器 | 说明 |
|--------|------|
| 子系统过滤 | 匹配 target_subsystem 及其相关子系统 |
| Bug类型过滤 | 精确或松弛匹配 bug_type |
| 版本过滤 | 基于内核版本的日期推断 |
| 去重 | commit_hash 去重 |
| 关键词过滤 | 根据 suggested_keywords 过滤标题 |

**子系统关系网**: 定义了子系统之间的父子关系和相关关系。例如 `mm` 相关于 `fs, block, kernel`。

### Phase 3: BGE Rerank (语义重排)

**目标**: 使用交叉编码器进行深度语义排序。

**BGE-Reranker-v2-m3 特性**:
- Cross-encoder 架构: 联合编码 (query, document)，捕获交互语义
- 与 BGE-M3 (Bi-encoder) 互补: Bi-encoder 快速召回，Cross-encoder 精准排序
- 仅对 Top-50~100 候选做交叉编码，兼顾精度和速度

**降级策略**: sentence-transformers 不可用时，使用基于关键词重叠的启发式打分。

### Phase 4: LLM Judge (因果评分)

**目标**: 利用大模型从因果关联角度判断补丁是否真正解决问题。

**不同于语义相似度**: LLM Judge 能够理解:
- 补丁是否修复了相同的根因 (而非表面相似的描述)
- 补丁的修复模式是否与故障特征匹配
- 补丁是否在同一子系统/函数路径中

**仅在 deep 模式下启用**，以控制延迟和 API 成本。

---

## 3. 子模块说明

### 3.1 recall — 向量召回

**核心功能**:
- `recall_candidates()`: 从向量库召回 Top-K 候选
- `recall_from_rootcause()`: ★ 推荐 — 从 RootCauseResult 直接召回，自动提取 retrieval_query
- `batch_recall()`: 批量查询
- `encode_query()`: 查询文本 → BGE-M3 向量
- `get_recall_stats()`: 召回统计 (子系统/Bug类型分布)

**设计要点**: 优先使用 `retrieval_query` 字段 — 保证在线查询与离线索引时的 embedding 文本结构对称。

### 3.2 filter — 规则过滤

**核心功能**:
- `filter_by_subsystem()`: 子系统过滤 (含相关系统)
- `filter_by_bug_type()`: Bug 类型过滤 (含相关类型)
- `filter_by_kernel_version()`: 版本过滤
- `filter_duplicates()`: 去重
- `filter_by_keywords()`: 关键词过滤
- `boost_security_fixes()`: CVE/Fixes 标签加权
- `apply_filters()`: ★ 流水线 — 应用所有过滤器
- `build_milvus_filter_expr()`: 构造 Milvus 标量过滤表达式

**19 个支持的子系统**: mm, fs, net, block, kernel, drivers, arch, bpf, security, kvm, rcu, cgroup, nfs, usb, pci, nvme, scsi, crypto, power

### 3.3 rerank — 语义重排

**核心功能**:
- `BGEReranker`: BGE-Reranker-v2 封装
- `llm_judge_scores()`: LLM 因果评分
- `fuse_scores()`: 多维度评分融合 (向量 + Reranker + LLM)
- `rerank_candidates()`: ★ 完整重排流程

**评分融合权重** (可配置):
| 维度 | 权重 | 说明 |
|------|------|------|
| Vector Score | 0.2 | 基础语义相似度 |
| Reranker Score | 0.4 | 交叉编码器深度语义 |
| LLM Judge | 0.4 | 大模型因果推理 |

**数据结构**:
- `RankedItem`: 单个排序结果 (含 rank, 多维分数, 排名理由)
- `RankedResult`: 完整排序结果 (含 Top-K items + 性能指标)

### 3.4 pipeline — 检索流水线

**核心功能**:
- `run_retrieval_pipeline()`: ★ 主入口 — 完整检索流水线
- `quick_search()`: 快速文本搜索 (无需分析)
- `search_by_bug_type()`: 按 Bug 类型搜索

**三种检索模式**:

| 模式 | 阶段 | 延迟 | 精度 | 适用场景 |
|------|------|------|------|---------|
| `fast` | Recall + Filter | <100ms | 中 | 快速诊断/交互式查询 |
| `standard` | + Rerank | <1s | 高 | 正式诊断/补丁推荐 |
| `deep` | + LLM Judge | 2-10s | 最高 | 关键问题/精确修复 |

---

## 4. 数据流

### 在线检索流程

```
用户输入 (dmesg / vmcore)
        │
        ▼
┌─────────────────┐
│ Analyzer         │  Phase 1: 特征提取 (dmesg regex + LLM + vmcore drgn)
│                  │  Phase 2: 根因抽象 (28 rules + LLM hybrid)
│                  │  Output: RootCauseResult.retrieval_query
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Recall           │  BGE-M3 编码 → Milvus/FAISS Top-K
│                  │  retrieval_query → query_vector → SearchResult
└────────┬────────┘
         │ Top-K candidates
         ▼
┌─────────────────┐
│ Filter           │  子系统/版本/Bug类型 硬过滤 + 安全补丁加权
└────────┬────────┘
         │ Filtered candidates
         ▼
┌─────────────────┐
│ Rerank           │  BGE-Reranker-v2 交叉编码 → [可选] LLM Judge
│                  │  多维度评分融合 → 综合排名
└────────┬────────┘
         │ RankedResult
         ▼
   输出: 排序后的补丁推荐 (含可解释排名理由)
```

---

## 5. 检索模式

### Fast 模式

```python
from src.retriever import run_retrieval_pipeline, RetrievalMode

result = run_retrieval_pipeline(
    rootcause_result,
    mode=RetrievalMode.FAST,
    top_k=50,
)
```

- 仅执行 Recall + Filter
- 毫秒级响应
- 适合交互式场景

### Standard 模式 (推荐)

```python
result = run_retrieval_pipeline(
    rootcause_result,
    mode=RetrievalMode.STANDARD,
    top_k=100,
)
```

- Recall + Filter + BGE Rerank
- 秒级响应
- 精度与速度的最佳平衡

### Deep 模式

```python
result = run_retrieval_pipeline(
    rootcause_result,
    mode=RetrievalMode.DEEP,
    top_k=100,
)
```

- 完整四阶段: + LLM Judge
- 最高精度
- 适合关键问题诊断

---

## 6. 使用指南

### 基本用法 — 从 dmesg 到补丁推荐

```python
from src.analyzer import run_analysis_pipeline
from src.retriever import run_retrieval_pipeline

# Step 1: 分析宕机日志
analysis = run_analysis_pipeline(dmesg_content=dmesg_log)

# Step 2: 检索匹配的补丁
result = run_retrieval_pipeline(analysis, mode="standard", top_k=100)

# Step 3: 查看推荐
for item in result.top(10):
    print(f"#{item.rank} [{item.subsystem}/{item.bug_type}] {item.subject}")
    print(f"   Score: {item.final_score:.3f} | {item.rank_reason}")
```

### 快速搜索

```python
from src.retriever import quick_search

# 直接输入关键词搜索
hits = quick_search("use after free in net/tcp.c", top_k=20)
for item in hits.top(5):
    print(item.subject)
```

### 按 Bug 类型搜索

```python
from src.retriever import search_by_bug_type

# 查找特定类型 Bug 的已知修复
hits = search_by_bug_type("deadlock", subsystem="kernel", top_k=50)
```

### 获取检索统计

```python
from src.retriever.recall import get_recall_stats

stats = get_recall_stats(search_result)
print(f"Hits: {stats['hit_count']}")
print(f"Avg Distance: {stats['avg_distance']:.4f}")
print(f"Subsystems: {stats['subsystems']}")
print(f"Bug Types: {stats['bug_types']}")
```

### 构造 Milvus 过滤表达式

```python
from src.retriever.filter import build_milvus_filter_expr

expr = build_milvus_filter_expr(
    subsystem="mm",
    bug_type="use_after_free",
    date_from="2024-01-01",
    min_score=6.0,
)
print(expr)
# '(subsystem=="mm" || subsystem=="fs" || ...) && bug_type=="use_after_free" && date>="2024-01-01" && score>=6.0'
```

---
