# Core.LinuxCommit 项目优化方案

> **分析日期**: 2026-06-09  
> **目标**: 根据赛题评审要点，评估项目完成情况并给出优化方案

---

## 目录

1. [总体评估](#1-总体评估)
2. [各模块完成情况](#2-各模块完成情况)
3. [核心瓶颈分析](#3-核心瓶颈分析)
4. [优化任务清单](#4-优化任务清单)
5. [评审要点对照](#5-评审要点对照)
6. [执行路线图](#6-执行路线图)
7. [风险与注意事项](#7-风险与注意事项)

---

## 1. 总体评估

| 维度 | 状态 | 说明 |
|------|------|------|
| **架构设计** | ✅ 完整 | 离线治理 + 在线分析的 RAG 架构，四阶段检索设计，对标工业界最佳实践 |
| **代码总量** | ✅ ~18,000+ 行 | Python 后端 ~15,000 行，Vue 前端 ~3,300 行，全部为实质性代码 |
| **模块覆盖** | ✅ 12 个核心模块 | analyzer / collector / indexer / retriever / generator / knowledge / api / frontend 全覆盖 |
| **前端** | ✅ 完整可运行 | 5 个页面 (Dashboard / CrashAnalysis / KnowledgeBase / History / LlmExplain) |
| **领域知识** | ✅ 深度建模 | 28 条专家规则 + 9 种 Bug 模式 + 6 种锁类型 + 12 个子系统知识图谱 |
| **真实数据链路** | ❌ 未打通 | Linux 内核源码已 clone (5.3GB)，但 commit 未向量化入库 |
| **LLM API** | ❌ 未配置 | 所有 LLM 调用点使用 `sk-placeholder`，需替换为真实 API key |
| **模型权重** | ❌ 未下载 | BGE-M3 / BGE-Reranker-v2 的实际权重文件未下载到本地 |
| **测试** | ❌ 几乎为空 | 仅 14 行占位测试，无单元测试、无集成测试、无自测案例 |
| **自测验证** | ❌ 未做 | 无 Top-3 命中率数据、无算法对比实验、无消融实验 |

---

## 2. 各模块完成情况

### 2.1 已完成且质量较高的模块 (可直接使用)

| 模块 | 路径 | 行数 | 完成度 | 质量评价 |
|------|------|------|--------|----------|
| **根因分析器** | `src/analyzer/rootcause/` | 1,744 | 95% | ⭐⭐⭐⭐⭐ 28 条专家规则 + 4 层分层分析 + LLM 协同，架构优秀 |
| **dmesg 解析** | `src/analyzer/dmesg/` | 750 | 95% | ⭐⭐⭐⭐⭐ 20+ 种 Panic 模式正则 + LLM 深度分析 + 降级策略 |
| **vmcore 解析** | `src/analyzer/vmcore/` | 561 | 80% | ⭐⭐⭐⭐ drgn 集成完整，调用栈提取、内核对象提取、特征融合 |
| **向量数据库层** | `src/indexer/milvus/` | 995 | 90% | ⭐⭐⭐⭐⭐ Milvus + FAISS 双后端，自动降级，混合检索 + 标量过滤 |
| **Embedding 引擎** | `src/indexer/embedding/` | 330 | 85% | ⭐⭐⭐⭐ BGE-M3 封装，GPU 自动检测，mock 降级策略 |
| **索引流水线** | `src/indexer/pipeline/` | 554 | 85% | ⭐⭐⭐⭐⭐ ★ 对称 Root Cause Embedding 是核心创新点 ★ |
| **Reranker** | `src/retriever/rerank/` | 588 | 85% | ⭐⭐⭐⭐ BGE-Reranker-v2 + LLM Judge + 多维度评分融合 |
| **规则过滤** | `src/retriever/filter/` | 505 | 90% | ⭐⭐⭐⭐⭐ 子系统层级 + 关联子系统 + 多维度过滤流水线 |
| **检索流水线** | `src/retriever/pipeline/` | 387 | 85% | ⭐⭐⭐⭐ fast / standard / deep 三种模式，架构清晰 |
| **召回模块** | `src/retriever/recall/` | 191 | 80% | ⭐⭐⭐⭐ 查询编码 + 向量召回 + 批量查询 |
| **Bug 模式知识库** | `src/knowledge/bug_patterns/` | 595 | 90% | ⭐⭐⭐⭐⭐ 9 种 Bug 类型 + 症状/原因/修复/检测工具的完整知识 |
| **锁规则知识库** | `src/knowledge/lock_rules/` | 455 | 90% | ⭐⭐⭐⭐⭐ 6 种锁类型 + 5 种死锁模式 + 8 条锁排序规则 |
| **子系统图谱** | `src/knowledge/subsystem_graph/` | 478 | 90% | ⭐⭐⭐⭐⭐ 12 个子系统 + 层级/耦合/调用关系 |
| **报告生成** | `src/generator/report/` | 618 | 85% | ⭐⭐⭐⭐ Markdown / JSON 双格式 + LLM 增强可选 |
| **Prompt 工程** | `src/generator/prompt/` | 437 | 85% | ⭐⭐⭐⭐ 场景化模板 + Few-shot 示例 + 结构化约束 |
| **LLM 客户端** | `src/generator/llm/` | 363 | 80% | ⭐⭐⭐⭐ OpenAI 兼容接口封装 |
| **数据采集器** | `src/collector/` | 1,486 | 90% | ⭐⭐⭐⭐⭐ PyDriller 深度集成，流式遍历，O(1) 内存，百万级友好 |
| **公共工具** | `src/common/` | 1,284 | 80% | ⭐⭐⭐⭐ loguru 日志 + 异常体系 + 工具函数 |
| **API 层** | `src/api/` | ~1,500 | 70% | ⭐⭐⭐ FastAPI + 中间件 + 路由完整，但核心用 mock 数据 |
| **前端** | `frontend/` | 3,280 | 80% | ⭐⭐⭐⭐ Vue 3 + Element Plus，5 页面完整，暗色专业主题 |

### 2.2 各模块技术亮点

#### ★ 核心创新：对称 Root Cause Embedding (indexer/pipeline)

```text
离线侧 (Commit)                   在线侧 (宕机日志)
     │                                  │
CommitInfo → CrashFeature              dmesg → CrashFeature
     │                                  │
     ▼                                  ▼
RootCauseAnalyzer.analyze()    RootCauseAnalyzer.analyze()
     │                                  │
     ▼                                  ▼
build_retrieval_query()        build_retrieval_query()
    (6层语义融合)                 (6层语义融合)
     │                                  │
     ▼                                  ▼
 BGE-M3 编码 → Milvus         BGE-M3 编码 → Milvus Search
```

这是解决 **"宕机现象 ≠ commit 描述"语义鸿沟** 的关键设计，两端使用相同的分析引擎。

#### ★ 四阶段检索架构 (retriever/pipeline)

```text
Phase 1: Vector Recall  (Milvus/FAISS Top-100)
    ↓
Phase 2: Rule Filter    (子系统/版本/Bug类型 硬过滤)
    ↓
Phase 3: BGE Rerank     (Cross-encoder 深度语义重排)
    ↓
Phase 4: LLM Judge      (大模型因果关联评分 → Top-3)
```

#### ★ 领域知识融合 (knowledge/)

- `bug_patterns`: 9 种 Bug 类型的完整知识 (症状→原因→修复模式→检测工具→内核配置)
- `lock_rules`: 6 种锁类型 + 5 种死锁模式 + 8 条锁排序规则 + 调用栈锁分析
- `subsystem_graph`: 12 个子系统 + 层级关系 + 耦合关系 + 调用关系

---

## 3. 核心瓶颈分析

### 🔴 致命问题

| # | 问题 | 影响 | 涉及文件 |
|---|------|------|----------|
| 1 | **API 使用 Mock 数据** | `/analyze` 用硬编码的 mock patches，`/search` 用硬编码的 `_MOCK_COMMITS`，系统完全不具备真实检索能力 | `src/api/routers/analyze.py:213-265`<br>`src/api/routers/search.py:19-104`<br>`src/api/routers/stats.py:17-57` |
| 2 | **Linux Commit 未索引** | 5.3GB 内核源码已 clone 到 `/home/lkx/文档/内核比赛/linux`，但未运行过采集+向量化流程，向量库为空 | `data/` 目录为空 |
| 3 | **测试几乎为空** | 仅 14 行占位测试，无法验证系统正确性，达不到赛题 "自测验证 + 消融实验" 要求 | `tests/` 目录 |

### 🟠 重要问题

| # | 问题 | 影响 | 涉及文件 |
|---|------|------|----------|
| 4 | **LLM API Key 未配置** | 所有 LLM 调用使用 `sk-placeholder`，导致 LLM 增强功能全部不可用 | `src/analyzer/dmesg/__init__.py:481`<br>`src/analyzer/rootcause/llm_rootcause.py:145`<br>`src/retriever/rerank/__init__.py:342` 等 |
| 5 | **模型权重未下载** | BGE-M3 (~2GB) 和 BGE-Reranker-v2-m3 (~1GB) 首次运行时会自动下载，但未预热 | `src/indexer/embedding/__init__.py`<br>`src/retriever/rerank/__init__.py` |
| 6 | **缺少索引启动脚本** | 没有一键运行的全量索引脚本，需要手动编写 | 需要新建 |

### 🟡 加分项缺失

| # | 问题 | 说明 |
|---|------|------|
| 7 | **Reranker 未微调** | 赛题指南明确指出这是高分关键："reranker 决定 top3 命中率" |
| 8 | **Root Cause 分类器未训练** | 可 LoRA 微调小模型做根因分类，提升准确率 |
| 9 | **缺乏自测数据和消融实验** | 无法展示系统在不同宕机类型上的表现和算法对比 |

---

## 4. 优化任务清单

### 第一优先级：打通真实数据链路 🔴 (预计 2-3 天)

> **目标**: 让系统能真正运行，实现 "日志 → Top-K 相关补丁" 的完整链路

#### 任务 1.1：创建全量 Commit 索引脚本

**新建文件**: `scripts/index_all_commits.py`

```python
#!/usr/bin/env python3
"""全量 Linux Kernel Commit 索引脚本

Usage:
    python scripts/index_all_commits.py --repo-path data/linux --batch-size 1000
"""

import argparse
import time
from datetime import datetime

from src.collector import collect_commits_stream
from src.indexer.pipeline import index_commits
from src.indexer.embedding import get_encoder


def main():
    parser = argparse.ArgumentParser(description="Index all Linux kernel commits")
    parser.add_argument("--repo-path", default="data/linux", help="Path to Linux kernel repo")
    parser.add_argument("--batch-size", type=int, default=1000, help="Index batch size")
    parser.add_argument("--limit", type=int, default=0, help="Max commits (0=unlimited)")
    parser.add_argument("--since", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--no-root-cause", action="store_true", help="Disable Root Cause analysis")
    args = parser.parse_args()

    # 1. 预热 encoder (下载模型权重)
    print("[1/3] Loading BGE-M3 encoder...")
    encoder = get_encoder()
    encoder.encode(["warmup text"])  # 触发模型下载
    print(f"      Encoder ready: dim={encoder.dimension}, device={encoder.device}")

    # 2. 流式收集 + 分批索引
    print(f"[2/3] Collecting commits from {args.repo_path}...")
    batch = []
    total = 0
    t_start = time.time()

    kwargs = {"repo_path": args.repo_path, "only_no_merge": True}
    if args.since:
        kwargs["since"] = datetime.fromisoformat(args.since)
    if args.limit > 0:
        kwargs["limit"] = args.limit

    for commit in collect_commits_stream(**kwargs):
        batch.append(commit)
        if len(batch) >= args.batch_size:
            n = index_commits(
                batch,
                batch_size=64,
                show_progress=False,
                create_collection=(total == 0),
                use_root_cause=not args.no_root_cause,
            )
            total += n
            elapsed = time.time() - t_start
            print(f"      Indexed {total} commits ({n} in batch, {total/elapsed:.1f} commits/sec)")
            batch = []

    # 处理剩余
    if batch:
        n = index_commits(
            batch, batch_size=64, create_collection=(total == 0),
            use_root_cause=not args.no_root_cause,
        )
        total += n

    # 3. 持久化
    print(f"[3/3] Saving index...")
    from src.indexer.milvus import get_milvus_client
    get_milvus_client().save()

    elapsed = time.time() - t_start
    print(f"\nDone! Indexed {total} commits in {elapsed/3600:.1f} hours")
    print(f"Average speed: {total/elapsed:.1f} commits/sec")


if __name__ == "__main__":
    main()
```

**预计耗时**:
| 阶段 | GPU | CPU |
|------|-----|-----|
| Commit 采集 (100万) | ~2h | ~2h |
| RootCause 分析 | ~1h | ~3h |
| BGE-M3 向量化 | ~6h | ~24-48h |
| FAISS 索引构建 | ~0.5h | ~0.5h |
| **总计** | **~10h** | **~30-53h** |

> **建议**: 先用 `--limit 10000` 跑通流程，确认无误后再全量执行。

#### 任务 1.2：修改 API 分析路由对接真实检索

**修改文件**: `src/api/routers/analyze.py`

将 `_simulate_analysis` 函数替换为：

```python
def _run_real_analysis(task_id: str, request: AnalyzeRequest) -> None:
    """真实分析流水线 — 对接 RAG pipeline"""
    from src.services import run_online_diagnosis

    steps = []
    try:
        _save_task(task_id, {"status": "running", "progress": 0.1})

        # 运行完整的在线诊断
        result = run_online_diagnosis(
            dmesg_content=request.log_content,
            use_llm=request.enable_llm_explanation,
            retrieval_mode="standard",
            top_k=100,
        )

        root_cause_info = None
        if result.root_cause_result:
            rc = result.root_cause_result
            root_cause_info = RootCauseInfo(
                root_cause=rc.root_cause,
                subsystem=getattr(rc.crash_feature, "subsystem", "unknown"),
                confidence=rc.score,
                summary=rc.reason,
                key_symptoms=rc.causal_chain,
            )

        matched_patches = []
        if result.retrieval_result:
            for item in result.retrieval_result.top(request.top_k):
                matched_patches.append(MatchedPatch(
                    rank=item.rank,
                    commit=CommitInfo(
                        commit_id=item.commit_hash,
                        title=item.subject,
                        subsystem=item.subsystem,
                        bug_type=item.bug_type,
                    ),
                    relevance_score=item.final_score,
                    rerank_score=item.reranker_score,
                    match_reason=item.rank_reason,
                ))

        _save_task(task_id, {
            "status": "completed",
            "progress": 1.0,
            "root_cause": root_cause_info,
            "matched_patches": matched_patches,
            "completed_at": datetime.utcnow(),
        })

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        _save_task(task_id, {"status": "failed", "error": str(e)})
```

#### 任务 1.3：修改搜索路由对接真实向量库

**修改文件**: `src/api/routers/search.py`

- 删除 `_MOCK_COMMITS` 硬编码数据
- 改为调用 `src.retriever.pipeline.quick_search()` 实现真实检索
- 分面统计从检索结果的 metadata 中聚合

#### 任务 1.4：修改统计路由对接真实数据

**修改文件**: `src/api/routers/stats.py`

- 删除全部 mock 数据
- 从 `get_milvus_client().get_stats()` 获取真实的向量库统计
- 子系统/Bug类型分布从索引元数据中聚合

---

### 第二优先级：补充测试与验证体系 🟠 (预计 2-3 天)

> **目标**: 建立完整的测试体系，准备自测案例和实验数据

#### 任务 2.1：准备测试用宕机日志

**新建目录**: `tests/fixtures/`

| 文件 | 内容 | 期望结果 |
|------|------|----------|
| `dmesg_hardlockup.txt` | NMI watchdog 硬锁死日志 | bug_type=hang, subsystem=kernel |
| `dmesg_softlockup.txt` | CPU 软锁定日志 | bug_type=hang, subsystem=kernel |
| `dmesg_uaf.txt` | KASAN use-after-free 日志 | bug_type=use_after_free, subsystem=mm |
| `dmesg_list_corruption.txt` | list_del corruption 日志 | bug_type=memory_corruption, subsystem=mm |
| `dmesg_null_pointer.txt` | NULL pointer dereference 日志 | bug_type=null_pointer, subsystem=drivers |
| `dmesg_deadlock.txt` | lockdep 死锁检测日志 | bug_type=deadlock, subsystem=fs |
| `dmesg_oom.txt` | Out of memory 日志 | bug_type=memory_leak, subsystem=mm |
| `dmesg_rcu_stall.txt` | RCU 宽限期停滞日志 | bug_type=hang, subsystem=rcu |
| `dmesg_double_free.txt` | KASAN double-free 日志 | bug_type=double_free, subsystem=mm |
| `dmesg_page_fault.txt` | 内核页错误日志 | bug_type=memory_corruption, subsystem=mm |

#### 任务 2.2：编写核心模块单元测试

```text
tests/
├── __init__.py
├── conftest.py                    # pytest fixtures
├── fixtures/                      # 测试数据
│   ├── dmesg_hardlockup.txt
│   ├── dmesg_uaf.txt
│   └── ... (as listed above)
├── test_dmesg_parser.py           # dmesg 解析器测试
├── test_root_cause.py             # 28 条专家规则测试
├── test_embedding.py              # BGE-M3 编码测试
├── test_retriever_pipeline.py     # 检索流水线测试
├── test_filter.py                 # 规则过滤测试
├── test_rerank.py                 # Reranker 测试
├── test_knowledge.py              # 知识库查询接口测试
└── test_integration.py            # 端到端集成测试
```

**test_root_cause.py 示例**:

```python
"""专家规则测试 — 验证 28 条规则的匹配准确性"""
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.mark.parametrize("fixture_file,expected_bug_type,expected_subsystem", [
    ("dmesg_hardlockup.txt", "hang", "kernel"),
    ("dmesg_softlockup.txt", "hang", "kernel"),
    ("dmesg_uaf.txt", "use_after_free", "mm"),
    ("dmesg_list_corruption.txt", "memory_corruption", "mm"),
    ("dmesg_null_pointer.txt", "null_pointer", "drivers"),
    ("dmesg_deadlock.txt", "deadlock", "fs"),
    ("dmesg_oom.txt", "memory_leak", "mm"),
    ("dmesg_rcu_stall.txt", "hang", "rcu"),
    ("dmesg_double_free.txt", "double_free", "mm"),
    ("dmesg_page_fault.txt", "memory_corruption", "mm"),
])
def test_root_cause_bug_type(fixture_file, expected_bug_type, expected_subsystem):
    """验证根因分析器对各类宕机日志的 bug_type 识别准确率"""
    dmesg_content = (FIXTURES_DIR / fixture_file).read_text()
    
    from src.analyzer.dmesg import parse_dmesg
    from src.analyzer.rootcause import abstract_root_cause
    
    feature = parse_dmesg(dmesg_content)
    result = abstract_root_cause(feature)
    
    assert result.bug_type == expected_bug_type, \
        f"Expected {expected_bug_type}, got {result.bug_type}"
    assert result.score >= 0.3, f"Confidence too low: {result.score}"
```

#### 任务 2.3：端到端集成测试 + Top-3 命中率计算

```python
"""集成测试：端到端验证 + Top-3 命中率"""
def test_end_to_end_top3_accuracy():
    """在已知的 Fixes 标签 commit 对上测试 Top-3 命中率"""
    # 1. 从 Linux kernel 仓库中提取 Fixes: 标签的 commit 作为 ground truth
    # 2. 将 bug 引入 commit 的 message 作为"宕机日志"输入
    # 3. 检查 fix commit 是否出现在 Top-3 结果中
    from src.collector.git import traverse_commits
    
    hits = 0
    total = 0
    
    for commit in traverse_commits("data/linux", only_no_merge=True, limit=1000):
        fix_tags = commit.fix_tags  # 需要 parser 中解析
        if not fix_tags:
            continue
        
        # 这里需要根据 Fixes: 标签找到对应的 fix commit
        # 然后以引入 commit 的 message 作为查询
        # ...（具体实现）
    
    accuracy = hits / max(total, 1)
    print(f"Top-3 accuracy: {accuracy:.1%}")
    assert accuracy >= 0.60, f"Target 60%, got {accuracy:.1%}"
```

---

### 第三优先级：核心创新点深挖 🟡 (预计 3-5 天)

> **目标**: 在核心技术点上拉开差距，冲击高分

#### 任务 3.1：收集 Reranker 微调训练数据

**策略**: 利用 Linux 内核中 `Fixes:` 标签的 commit → 天然的 `(bug, fix)` 监督数据

```python
"""提取 Fixes 标签的训练数据"""
from src.collector.git import traverse_commits

training_pairs = []

for commit in traverse_commits("data/linux", only_no_merge=True):
    if not commit.fix_tags:
        continue
    
    # commit.fix_tags 形如 ["Fixes: abc123def456..."]
    for tag in commit.fix_tags:
        fixed_hash = tag.replace("Fixes:", "").strip()[:12]
        
        # 找到被修复的那个 commit
        buggy_commit = get_commit_info(fixed_hash, "data/linux")
        if buggy_commit:
            # 正样本: (buggy_commit.message, fix_commit)
            training_pairs.append({
                "query": buggy_commit.subject + "\n" + buggy_commit.body[:500],
                "positive": commit.subject + "\n" + commit.diff_content[:1000],
                "label": 1.0,
            })
```

**预期数据量**: Linux 内核中约 10-20% 的 commit 含 `Fixes:` 标签，保守估计可收集 5-10 万对训练数据。

#### 任务 3.2：微调 BGE-Reranker-v2-m3

```python
"""使用 sentence-transformers 微调 Reranker"""
from sentence_transformers import CrossEncoder, InputExample
from torch.utils.data import DataLoader

# 1. 加载基础模型
model = CrossEncoder("BAAI/bge-reranker-v2-m3")

# 2. 构造训练样本
train_examples = [
    InputExample(texts=[pair["query"], pair["positive"]], label=1.0)
    for pair in training_pairs
]

# 3. 微调
train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=16)
model.fit(
    train_dataloader=train_dataloader,
    epochs=1,
    warmup_steps=100,
    output_path="models/bge-reranker-v2-m3-finetuned",
)
```

#### 任务 3.3：对称 Root Cause 分析增强

**修改文件**: `src/indexer/pipeline/__init__.py`

当前 `_build_commit_root_cause_embedding_text` 仅使用规则引擎。增强方案：
- 对 `Fixes:` / `Cc: stable` 标签的 commit 增加加权信号
- 对 diff 中关键修复行做更精细的提取（增加 `synchronize_rcu`, `cond_resched`, `WRITE_ONCE/READ_ONCE` 等模式）
- 利用 subsystem_graph 中的耦合子系统信息扩展关联检索

---

### 第四优先级：工程完善 🟢 (预计 2-3 天)

> **目标**: 提升可演示性、可部署性、可维护性

#### 任务 4.1：LLM API 配置化

**修改文件**: `configs/config.yaml`

```yaml
llm:
  providers:
    deepseek:
      api_key: "${DEEPSEEK_API_KEY}"
      base_url: "https://api.deepseek.com/v1"
      model: "deepseek-chat"
    qwen:
      api_key: "${QWEN_API_KEY}"
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
      model: "qwen2.5-72b-instruct"
  default: "deepseek"
  retry:
    max_retries: 3
    backoff: "exponential"
```

#### 任务 4.2：完善 Docker 一键部署

**修改文件**: `docker/docker-compose.yml`

添加 Milvus standalone、Redis，并预构建 FAISS 索引镜像。

#### 任务 4.3：性能优化

- FAISS → Milvus 生产模式切换
- 查询向量 Redis 缓存
- BGE-M3 批处理大小调优
- API 响应时间 benchmark

---

## 5. 评审要点对照

| 评审维度 | 权重 | 当前得分 | 满分潜力 | 关键差距 | 补救措施 |
|----------|------|----------|----------|----------|----------|
| **语义理解能力** | 30% | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Root Cause Abstraction + 对称 Embedding 已设计但未验证 | 打通数据链路后验证并调优 |
| **领域知识融合** | 30% | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 已达到满分水平 | — |
| **场景泛化性** | 30% | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 覆盖 20+ 种 panic 类型 | — |
| **功能完整性** | 30% | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 全链路未打通 | 任务 1.1-1.4 |
| **数据规模与处理能力** | 30% | ⭐ | ⭐⭐⭐⭐⭐ | 内核源码已 clone 但未索引 | 任务 1.1 |
| **代码规范** | 15% | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Type hints / loguru / 模块化良好 | 补充部分 docstring |
| **性能效率** | 15% | ⭐⭐ | ⭐⭐⭐⭐ | 未进行 benchmark | 任务 4.3 |
| **可维护性** | 15% | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 异常处理 + 降级策略完善 | — |
| **解释性展示** | 15% | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 前端完整，但需真实数据演示 | 任务 1.2 |
| **直观性** | 15% | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 报告含因果链 + 评分依据 | — |
| **Demo 真实感** | 15% | ⭐⭐ | ⭐⭐⭐⭐⭐ | 当前为 mock 演示 | 任务 1.1-1.4 |
| **方案设计文档** | 10% | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | README 完整但缺实验数据 | 补充自测数据 |
| **自测验证** | 10% | ⭐ | ⭐⭐⭐⭐⭐ | 完全空白 | 任务 2.1-2.3 |
| **复现性** | 10% | ⭐⭐ | ⭐⭐⭐⭐ | Dockerfile 有但缺完整部署流程 | 任务 4.2 |

---

## 6. 执行路线图

```text
Week 1                            Week 2                            Week 3
│                                 │                                 │
├─ Day 1-2 ───────────────────────┤                                 │
│ 任务 1.1: 全量 Commit 索引      │                                 │
│ 任务 1.2: API 对接真实检索      │                                 │
│ 任务 1.3: 搜索/统计 对接真实数据│                                 │
│                                 │                                 │
├───────────────── Day 3-5 ───────┤                                 │
│                  │ 任务 2.1: 准备宕机日志 fixtures                │
│                  │ 任务 2.2: 编写核心模块单元测试                  │
│                  │ 任务 2.3: 端到端集成测试 + Top-3 命中率       │
│                                 │                                 │
├───────────────────────────────── Day 6-10 ──────────────────────┤
│                                 │ 任务 3.1: 收集 Reranker 训练数据│
│                                 │ 任务 3.2: 微调 Reranker         │
│                                 │ 任务 3.3: 对称 Root Cause 增强  │
│                                 │                                 │
├─────────────────────────────────────────── Day 11-14 ──────────┤
│                                 │ 任务 4.1: LLM API 配置化      │
│                                 │ 任务 4.2: Docker 一键部署      │
│                                 │ 任务 4.3: 性能优化 + benchmark  │
│                                 │                                 │
├─────────────────────────────────────────────────── Day 15 ────┤
│ 最终自测 + 演示准备 + 文档完善                                   │
│                                                                  │
▼                                                                  ▼
 最小可用版本 (Day 2)               高分版本 (Day 15)
 端到端跑通                         全链路优化 + 微调
```

### 里程碑定义

| 里程碑 | 时间 | 验收标准 |
|--------|------|----------|
| **M1: 最小可用** | Day 2 | 输入 dmesg 日志 → 返回 Top-5 commit（真实数据） |
| **M2: 质量验证** | Day 5 | 10 种宕机类型测试通过，Top-3 命中率 ≥ 50% |
| **M3: 性能达标** | Day 10 | 检索耗时 < 3 秒，Reranker 微调后 Top-3 ≥ 60% |
| **M4: 演示就绪** | Day 15 | Docker 一键部署 + 10 分钟流畅 Demo |

---

## 7. 风险与注意事项

### 7.1 时间风险

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| BGE-M3 在 CPU 上进阶时间过长 | 高 | 无法按时完成索引 | 优先使用 GPU；先用 10 万条验证流程，剩余异步索引 |
| DeepSeek API 限流 | 中 | LLM 增强功能不可用 | 做好降级策略（规则引擎兜底），LLM 不是核心路径 |
| PyDriller 在百万级仓库 OOM | 低 | 索引中断 | 流式遍历已实现，确认 batch_size 合理 |

### 7.2 技术决策建议

- **不要训练 LLM** — 赛题指南明确说不需要，使用现成的 DeepSeek/Qwen API
- **不要从头训练 Embedding** — BGE-M3 已是 SOTA，专注在检索策略和领域知识增强
- **优先投入 Reranker 微调** — 这是 "决定 top3 命中率" 的核心
- **保持规则和 LLM 的双轨架构** — 规则保证下限，LLM 提升上限

### 7.3 关键文件索引

参考赛题规则中的评审要点，以下文件直接影响各维度得分：

| 评审维度 | 关键文件 |
|----------|----------|
| 语义理解 | `src/analyzer/rootcause/__init__.py`, `src/indexer/pipeline/__init__.py` |
| 领域知识 | `src/knowledge/`, `src/analyzer/rootcause/__init__.py` (28规则) |
| 功能完整性 | `src/services/__init__.py`, `src/retriever/pipeline/__init__.py` |
| 代码质量 | `src/common/`, `src/models/__init__.py` |
| 解释性 | `src/generator/report/__init__.py`, `frontend/src/views/` |
| 测试 | `tests/` (需大量补充) |

---

*文档生成于 2026-06-09*
