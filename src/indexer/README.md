# Indexer — 索引与向量检索核心模块

> **Embedding Engine + Vector Database Layer + Indexing Pipeline**

负责将 Linux Commit 数据和宕机分析结果进行向量化编码，并管理向量数据库的存储与检索。是整个系统"离线数据治理"与"在线语义检索"的基础设施层。

---

## 目录

1. [模块架构](#1-模块架构)
2. [子模块说明](#2-子模块说明)
3. [数据流](#3-数据流)
4. [使用指南](#4-使用指南)
5. [竞赛要求对照](#5-竞赛要求对照)

---

## 1. 模块架构

```
src/indexer/
├── __init__.py            # 模块入口 — 统一导出所有公共 API
├── embedding/__init__.py  # ★ 向量编码引擎 — BGE-M3 + 批量编码 + GPU 加速
├── milvus/__init__.py     # ★ 向量数据库层 — Milvus (生产) + FAISS (本地) 双后端
├── pipeline/__init__.py   # ★ 索引流水线 — 离线构建 + 增量更新 + 在线查询
└── README.md              # 本文档
```

---

## 2. 子模块说明

### 2.1 embedding — 向量编码引擎

**职责**: 将文本转换为高维向量，是语义检索的基础。

**核心实现**:

| 功能 | 说明 |
|------|------|
| **BGE-M3 模型** | `BAAI/bge-m3` 首选，1024 维，中英双语，长文本 (8192 tokens) |
| **批量编码** | `batch_size` 可配 (默认 64)，百万级数据处理不 OOM |
| **GPU 加速** | 自动检测 CUDA/MPS，也可手动指定 `device="cuda:0"` |
| **延迟初始化** | 模型仅在首次 `encode()` 时加载，减少启动开销 |
| **降级策略** | sentence-transformers 不可用时使用 mock 编码器 (归一化随机向量)，不阻塞流程 |
| **多模型支持** | BGE-M3 (1024d) / GTE-Qwen2 (1536d) / bce-embedding (768d) / E5 (1024d) |

**向量维度参考**:

| 模型 | 维度 | 适用场景 |
|------|------|---------|
| `BAAI/bge-m3` | 1024 | ★ 首选，中英双语 + 代码 |
| `Alibaba-NLP/gte-Qwen2-1.5B-instruct` | 1536 | 代码+文本混合 |
| `maidalun1020/bce-embedding-base_v1` | 768 | 中文强 |
| `intfloat/e5-large-v2` | 1024 | 英文强 |

### 2.2 milvus — 向量数据库层

**职责**: 向量数据的存储、索引和相似度检索。双后端设计确保从开发到生产的平滑过渡。

**双后端架构**:

```
            ┌──────────────────────┐
            │    MilvusClient       │  统一接口
            │  (auto/milvus/faiss)  │
            └──────┬───────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
┌──────────────┐       ┌──────────────┐
│ MilvusBackend│       │ FAISSBackend │
│  (生产模式)   │       │  (本地/开发)  │
├──────────────┤       ├──────────────┤
│ PyMilvus     │       │ faiss-cpu    │
│ IVF_FLAT     │       │ IndexFlatIP  │
│ HNSW         │       │ IndexIVFFlat │
│ 混合检索      │       │ 后过滤       │
│ 分区支持      │       │ 持久化       │
│ 百万级向量    │       │ 快速启动      │
└──────────────┘       └──────────────┘
```

**Milvus Schema 设计** (支持混合检索):

| 字段 | 类型 | 说明 |
|------|------|------|
| `commit_hash` | VARCHAR(64) | 提交哈希 |
| `subject` | VARCHAR(512) | 提交标题 |
| `subsystem` | VARCHAR(64) | 子系统 (可过滤) |
| `bug_type` | VARCHAR(64) | Bug 类型 (可过滤) |
| `author` | VARCHAR(128) | 作者 |
| `date` | VARCHAR(32) | 日期 (可过滤) |
| `files_changed` | VARCHAR(2048) | 修改文件列表 |
| `fix_tags` | VARCHAR(512) | 修复标签 (Fixes/CVE) |
| `score` | FLOAT | Commit 重要性分数 |
| `embedding` | FLOAT_VECTOR(1024) | BGE-M3 向量 |

**混合检索示例**: 向量相似度 + 标量过滤 → `subsystem=="mm" && bug_type=="deadlock"`

### 2.3 pipeline — 索引流水线

**职责**: 串联 embedding 和 milvus，提供离线索引构建和在线查询的编排。

**核心功能**:

| 功能 | 函数 | 说明 |
|------|------|------|
| 离线批量索引 | `index_commits()` | 全量构建向量索引 (支持 `use_root_cause` 参数) |
| 增量索引 | `index_commits_incremental()` | 增量添加新 commit |
| 在线查询向量 | `get_query_vector()` | 分析结果 → 查询向量 (优先使用 retrieval_query) |
| 一站式检索 | `search_similar_commits()` | 分析结果 → Top-K 候选 commit |
| ★ Embedding 文本构造 | `prepare_commit_embedding_text()` | ★ 通过 RootCauseAnalyzer (28规则+4层分析) 生成与在线侧对称的 embedding 文本 |
| 检索查询构造 | `prepare_rootcause_embedding_text()` | RootCauseResult → 查询文本 |
| ★ 对称分析辅助 | `_commit_to_crash_feature()` | CommitInfo → CrashFeature 映射 |
| | `_enhance_fix_hints_with_diff()` | 将 diff 分析结果融合进 fix_hints |
| | `_build_commit_root_cause_embedding_text()` | 完整的对称 embedding 文本构造流程 |

---

## 3. 数据流

### 离线索引 (Offline)

```
Linux Kernel Git Repo
        │
        ▼
┌─────────────────┐
│ Collector        │  PyDriller 遍历 → CommitInfo 列表
└────────┬────────┘
         │ List[CommitInfo]
         ▼
┌─────────────────┐
│ prepare_commit   │  ★ Root Cause 对称分析:
│ _embedding_text  │  1. CommitInfo → CrashFeature
│ (use_root_cause  │  2. RootCauseAnalyzer (28规则+4层分析)
│  =True, 默认)     │  3. 增强 fix_hints (融入 diff 证据)
│                  │  4. build_retrieval_query (6层语义融合)
│                  │  5. 追加 KeyDiffLines
└────────┬────────┘
         │ 优化后的文本
         ▼
┌─────────────────┐
│ BGE-M3 Encode   │  批量编码 (batch_size=64)
│ (GPU/CUDA)      │  normalize_embeddings=True
└────────┬────────┘
         │ shape (N, 1024) float32
         ▼
┌─────────────────┐
│ Milvus / FAISS   │  向量 + 元数据插入
│                  │  创建索引 (IVF_FLAT/HNSW)
│                  │  持久化
└────────┬────────┘
         │
         ▼
   ✓ 索引就绪: N 个 commit 可检索
```

### 在线查询 (Online)

```
dmesg / vmcore 输入
        │
        ▼
┌─────────────────┐
│ Analyzer         │  Phase 1: 特征提取
│                  │  Phase 2: 根因抽象 → RootCauseResult
└────────┬────────┘
         │ RootCauseResult.retrieval_query
         ▼
┌─────────────────┐
│ get_query_vector │  使用 retrieval_query 编码
│ BGE-M3 Encode   │
└────────┬────────┘
         │ shape (1024,) float32
         ▼
┌─────────────────┐
│ Vector Search    │  Milvus/FAISS 检索
│                  │  Top-K 候选 (K=100)
│                  │  可选: 标量过滤 (subsystem/bug_type/date)
└────────┬────────┘
         │ SearchResult (ids, distances, metadata)
         ▼
    下游: Retriever (rerank/filter)
```

---

## 4. 使用指南

### 4.1 离线构建索引

```python
from src.indexer import index_commits, get_index_stats

# 批量索引 (支持百万级数据)
n = index_commits(
    all_commits,
    batch_size=64,        # 编码批量大小
    show_progress=True,   # 显示进度条
    dim=1024,             # BGE-M3 维度
)

print(f"Indexed {n} commits")
print(get_index_stats())
```

### 4.2 增量索引

```python
from src.indexer import index_commits_incremental

# 只添加新增的 commit
new_commits = [...]  # 来自 git pull 的新提交
index_commits_incremental(new_commits, batch_size=64)
```

### 4.3 在线查询

```python
from src.indexer import search_similar_commits, get_query_vector

# 方式 1: 一站式检索 (推荐)
from src.analyzer import run_analysis_pipeline
result = run_analysis_pipeline(dmesg_content=dmesg_log)
hits = search_similar_commits(
    result,
    top_k=20,
    filter_expr='subsystem=="mm"',  # 可选: 按子系统过滤
)
for item in hits.to_dict_list():
    print(f"{item['subject'][:60]}: score={item['score']:.3f}")

# 方式 2: 手动分步
query_vec = get_query_vector(result)
client = get_milvus_client()
search_result = client.search(query_vec, top_k=10)
```

### 4.4 自定义 Embedding 文本

```python
from src.indexer import prepare_commit_embedding_text

# 查看 embedding 文本格式
commit = some_commit_info
text = prepare_commit_embedding_text(commit)
print(text)
# 输出:
# Title: fix race condition in list_del
# Subsystem: mm
# BugType: race_condition
# Files: mm/slab.c, include/linux/list.h
# CommitMessage: ...
# ...
# KeyDiffLines:
# spin_lock_irqsave(&list->lock, flags);
# ...
```

### 4.5 索引管理

```python
from src.indexer import get_milvus_client, get_index_stats, get_index_count

client = get_milvus_client()

# 检查索引状态
print(f"Backend: {client.active_backend}")
print(f"Total vectors: {client.count()}")
print(get_index_stats())

# 创建/重建 Collection
client.create_collection(dim=1024, index_type="IVF_FLAT", drop_if_exists=True)

# FAISS 模式持久化
client.save()
```

---

