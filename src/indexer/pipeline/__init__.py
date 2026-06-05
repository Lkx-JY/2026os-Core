"""索引流水线模块 — Indexing Pipeline

负责将 Commit 数据和宕机分析结果转换为向量并存入/查询向量库。
是整个系统"离线构建"与"在线查询"的编排层。

核心功能:
- 离线索引: 批量处理 Collector 收集的 Commit 数据，构建全量向量索引
- 在线查询: 将 Analyzer 输出的根因抽象结果实时转换为查询向量
- 增量索引: 支持增量添加新 commit 而不重建整个索引
- 批量处理: 分批编码 + 分批插入，支持百万级数据

设计要点:
- ★ 对称 Root Cause 分析: 离线侧 Commit 也通过 RootCauseAnalyzer (28规则+4层分析)，
  生成与在线侧 retrieval_query 结构对称的 embedding 文本，消除语义鸿沟
- embedding_text 语义增强拼接: 融合 RootCause + BugType + Subsystem + FixPattern + KeyFunctions + CausalChain
- 使用 RootCauseResult.retrieval_query 作为在线查询文本和离线 embedding 文本的统一格式
- 批处理流水线: encode_batch → insert_batch，控制内存峰值
"""

from __future__ import annotations
import numpy as np
from typing import List, Any, Optional, Callable
from ..embedding import encode_text, get_encoder
from ..milvus import get_milvus_client, SearchResult
from ...analyzer.models import CrashFeature


# ============================================================================
# embedding_text 构造 — 语义增强拼接 (含 Root Cause 对称分析)
# ============================================================================

def _commit_to_crash_feature(commit) -> "CrashFeature":
    """将 CommitInfo 映射为 CrashFeature，使 RootCauseAnalyzer 可以分析 Commit

    映射策略:
    - panic_msg ← commit.subject + body 摘要（作为"问题描述"）
    - subsystem / bug_type ← 直接复用 Collector 层已识别的值
    - call_trace ← [] (commit 没有内核调用栈)
    - extra_info.source ← "commit"

    Args:
        commit: CommitInfo 对象

    Returns:
        CrashFeature 对象
    """
    subject = getattr(commit, "subject", "")
    body = getattr(commit, "body", "")
    subsystem = getattr(commit, "subsystem", "unknown")
    bug_type = getattr(commit, "bug_type", "unknown")
    lock_added = getattr(commit, "lock_added", False)
    refcount_fix = getattr(commit, "refcount_fix", False)
    rcu_fix = getattr(commit, "rcu_fix", False)
    fix_tags = getattr(commit, "fix_tags", [])
    commit_hash = getattr(commit, "commit_hash", "")
    files_changed = getattr(commit, "files_changed", [])

    return CrashFeature(
        call_trace=[],
        subsystem=subsystem if subsystem else "unknown",
        bug_type=bug_type if bug_type else "unknown",
        kernel_version="",
        modules=[],
        panic_msg=f"{subject}\n{body[:500]}" if body else subject,
        extra_info={
            "source": "commit",
            "commit_hash": commit_hash,
            "files_changed": files_changed[:10],
            "lock_added": lock_added,
            "refcount_fix": refcount_fix,
            "rcu_fix": rcu_fix,
            "fix_tags": fix_tags,
        },
    )


def _enhance_fix_hints_with_diff(commit, analyzer_fix_hints: dict) -> dict:
    """将 commit 的 diff 分析结果 (lock_added/refcount_fix/rcu_fix) 融合进
    RootCauseAnalyzer 推断的 fix_hints，使 FixPattern 描述更精准。

    融合策略:
    - analyzer_fix_hints 中的 needs_* 标志保留（基于 bug_type 推断）
    - commit 的 diff 分析结果作为"已确认"的修复证据
    - suggested_search_keywords 合并去重

    Args:
        commit: CommitInfo 对象
        analyzer_fix_hints: RootCauseAnalyzer.infer_fix_patterns() 的输出

    Returns:
        增强后的 fix_hints dict
    """
    lock_added = getattr(commit, "lock_added", False)
    refcount_fix = getattr(commit, "refcount_fix", False)
    rcu_fix = getattr(commit, "rcu_fix", False)

    enhanced = dict(analyzer_fix_hints)

    # 确认标志 (diff 分析结果优先级更高)
    if lock_added:
        enhanced["needs_lock_fix"] = True
    if refcount_fix:
        enhanced["needs_refcount_fix"] = True
    if rcu_fix:
        enhanced["needs_rcu_fix"] = True

    # 合并搜索关键词
    existing_kw = set(enhanced.get("suggested_search_keywords", []))
    if lock_added:
        existing_kw.update(["spin_lock", "mutex_lock", "lock_irqsave"])
    if refcount_fix:
        existing_kw.update(["kref_get", "kref_put", "refcount_inc", "refcount_dec"])
    if rcu_fix:
        existing_kw.update(["kfree_rcu", "synchronize_rcu", "rcu_read_lock", "rcu_read_unlock"])
    enhanced["suggested_search_keywords"] = list(existing_kw)

    # 添加 diff_evidence 字段
    enhanced["diff_evidence"] = {
        "lock_added": lock_added,
        "refcount_fix": refcount_fix,
        "rcu_fix": rcu_fix,
    }

    return enhanced


def _build_commit_root_cause_embedding_text(commit) -> str:
    """通过 RootCauseAnalyzer 为 Commit 构造与在线侧对称的 embedding 文本。

    完整流程:
    1. CommitInfo → CrashFeature 映射
    2. RootCauseAnalyzer.analyze() → RootCauseResult (28规则+4层分析)
    3. 用 commit diff 分析结果增强 fix_hints
    4. build_retrieval_query() → 6层语义融合的 retrieval_query
    5. 追加 KeyDiffLines 提供代码级匹配信号

    Args:
        commit: CommitInfo 对象

    Returns:
        与在线侧 retrieval_query 结构对称的 embedding 文本
    """
    from ...analyzer.rootcause import (
        get_analyzer,
        build_retrieval_query,
    )

    # Step 1: CommitInfo → CrashFeature
    feature = _commit_to_crash_feature(commit)

    # Step 2: RootCauseAnalyzer 分析 (28规则+4层分层推断)
    analyzer = get_analyzer()
    result = analyzer.analyze(feature)

    # Step 3: 用 commit diff 分析结果增强 fix_hints
    analyzer_fix_hints = result.extra_info.get("fix_hints", {})
    enhanced_fix_hints = _enhance_fix_hints_with_diff(commit, analyzer_fix_hints)

    # Step 4: 重新构造 retrieval_query (使增强后的 fix_hints 生效)
    trace_analysis = result.extra_info.get("trace_analysis", {})
    retrieval_query = build_retrieval_query(
        feature=feature,
        root_cause=result.root_cause,
        bug_type=result.bug_type,
        causal_chain=result.causal_chain,
        fix_hints=enhanced_fix_hints,
        trace_analysis=trace_analysis,
    )

    # Step 5: 追加 KeyDiffLines (代码级匹配信号)
    diff = getattr(commit, "diff_content", "")
    if diff:
        key_fix_lines = _extract_key_diff_lines(diff, max_lines=20)
        if key_fix_lines:
            retrieval_query += f"\nKeyDiffLines:\n{key_fix_lines}"

    return retrieval_query


def prepare_commit_embedding_text(commit, use_root_cause: bool = True) -> str:
    """为 CommitInfo 构造语义增强的 embedding 文本

    支持两种模式:
    - use_root_cause=True (★ 推荐, 默认):
      通过 RootCauseAnalyzer (28规则+4层分析) 生成与在线侧 retrieval_query
      结构对称的 embedding 文本，消除"宕机描述"与"补丁描述"之间的语义鸿沟。

    - use_root_cause=False (降级, 兼容旧版):
      使用简单结构化标签拼接 (Title/Subsystem/BugType/LockAdded/RCUFix/RefcountFix)。

    设计原则 (参考赛题指导):
    - 不只是 message + diff 的简单拼接
    - 对称 Root Cause 分析: 在线侧和离线侧使用相同的分析引擎
    - 保留修复语义: lock_added/rcu_fix/refcount_fix 映射为自然语言 FixPattern
    - diff 内容截断保留关键修复逻辑

    Args:
        commit: CommitInfo 对象
        use_root_cause: 是否启用 Root Cause 对称分析 (默认 True)

    Returns:
        优化后的 embedding 文本
    """
    # ★ 新版: Root Cause 对称分析
    if use_root_cause:
        return _build_commit_root_cause_embedding_text(commit)

    # 降级: 原有简单标签拼接逻辑
    if hasattr(commit, "to_embedding_text"):
        base = commit.to_embedding_text()
    else:
        subject = getattr(commit, "subject", "")
        body = getattr(commit, "body", "")
        subsystem = getattr(commit, "subsystem", "unknown")
        bug_type = getattr(commit, "bug_type", "unknown")
        files = getattr(commit, "files_changed", [])
        fix_tags = getattr(commit, "fix_tags", [])
        lock_added = getattr(commit, "lock_added", False)
        rcu_fix = getattr(commit, "rcu_fix", False)
        refcount_fix = getattr(commit, "refcount_fix", False)
        diff = getattr(commit, "diff_content", "")

        base = f"""Title: {subject}
Subsystem: {subsystem}
BugType: {bug_type}
Files: {', '.join(files[:10])}
CommitMessage: {body[:2000]}
FixTags: {', '.join(fix_tags[:10])}
LockAdded: {lock_added}
RCUFix: {rcu_fix}
RefcountFix: {refcount_fix}"""

    # 附加 diff 中的关键修复行
    diff = getattr(commit, "diff_content", "")
    if diff:
        key_fix_lines = _extract_key_diff_lines(diff, max_lines=20)
        if key_fix_lines:
            base += f"\nKeyDiffLines:\n{key_fix_lines}"

    return base


def prepare_rootcause_embedding_text(result) -> str:
    """为 RootCauseResult 构造检索查询文本

    优先使用新版 analyzer 输出的 retrieval_query（已包含完整的语义融合），
    如果不存在则从字段拼接。

    Args:
        result: RootCauseResult 对象

    Returns:
        优化后的检索查询文本
    """
    # ★ 优先使用新版 retrieval_query
    if hasattr(result, "retrieval_query") and result.retrieval_query:
        return result.retrieval_query

    # 降级：从字段拼接
    root_cause = getattr(result, "root_cause", "")
    reason = getattr(result, "reason", "")
    causal_chain = getattr(result, "causal_chain", [])
    bug_type = getattr(result, "bug_type", "")
    keywords = getattr(result, "suggested_keywords", [])

    parts = [f"RootCause: {root_cause}", f"BugType: {bug_type}"]

    if hasattr(result, "crash_feature"):
        cf = result.crash_feature
        if getattr(cf, "panic_msg", ""):
            parts.append(f"PanicInfo: {cf.panic_msg}")
        if getattr(cf, "subsystem", "unknown") != "unknown":
            parts.append(f"Subsystem: {cf.subsystem}")

    parts.append(f"Reason: {reason}")

    if causal_chain:
        parts.append(f"CausalChain: {' -> '.join(causal_chain[:5])}")

    if keywords:
        parts.append(f"Keywords: {', '.join(keywords)}")

    return "\n".join(parts)


def _extract_key_diff_lines(diff_content: str, max_lines: int = 20) -> str:
    """从 diff 中提取关键的修复代码行

    只保留以 + 开头且包含关键修复模式的代码行:
    - 锁操作: spin_lock, mutex_lock, spin_unlock...
    - 内存操作: kfree, kmalloc, kref_get, kref_put...
    - RCU 操作: kfree_rcu, synchronize_rcu, rcu_read_lock...
    - 错误处理: NULL check, error handling, goto...
    """
    fix_keywords = [
        "spin_lock", "spin_unlock", "mutex_lock", "mutex_unlock",
        "kref_get", "kref_put", "kref_init",
        "refcount_inc", "refcount_dec",
        "kfree", "kmalloc", "kzalloc",
        "kfree_rcu", "synchronize_rcu", "rcu_read_lock", "rcu_read_unlock",
        "if (!", "if (!", "NULL", "null",
        "return -", "goto", "error",
        "BUG", "WARN",
        "atomic_inc", "atomic_dec", "atomic_read",
    ]

    key_lines = []
    for line in diff_content.split("\n"):
        if line.startswith("+"):
            line_lower = line.lower()
            if any(kw.lower() in line_lower for kw in fix_keywords):
                key_lines.append(line[1:].strip()[:120])  # 去掉 + 前缀，限制长度
                if len(key_lines) >= max_lines:
                    break

    return "\n".join(key_lines)


# ============================================================================
# 通用 embedding 文本准备
# ============================================================================

def prepare_embedding_text(data: Any, use_root_cause: bool = True) -> str:
    """智能路由：根据数据类型选择最合适的 embedding 文本构造方法

    Args:
        data: RootCauseResult / CommitInfo / 其他
        use_root_cause: CommitInfo 时是否启用 Root Cause 对称分析
    """
    # RootCauseResult (优先检查，因为它也有 to_embedding_text 或类似方法)
    if hasattr(data, "root_cause"):
        return prepare_rootcause_embedding_text(data)

    # CommitInfo
    if hasattr(data, "commit_hash"):
        return prepare_commit_embedding_text(data, use_root_cause=use_root_cause)

    # 有 to_embedding_text 方法
    if hasattr(data, "to_embedding_text"):
        return data.to_embedding_text()

    # 兜底
    return str(data)


# ============================================================================
# 离线索引流水线
# ============================================================================

def index_commits(
    commits: List[Any],
    batch_size: int = 64,
    show_progress: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    create_collection: bool = True,
    dim: int = 1024,
    use_root_cause: bool = True,
) -> int:
    """离线流程：对 Commit 进行批量向量化并存入向量库

    处理流程:
    1. 构造语义增强的 embedding 文本 (★ 默认通过 RootCauseAnalyzer 对称分析)
    2. 分批向量化 (batch_size 控制内存)
    3. 分批插入向量库 (batch_size=1000 控制网络负载)
    4. 持久化 (FAISS 模式)

    Args:
        commits: CommitInfo 对象列表
        batch_size: 向量化批量大小 — 百万级数据建议 32-128
        show_progress: 是否显示进度条
        progress_callback: 进度回调 (current, total)
        create_collection: 是否自动创建 Collection
        dim: 向量维度
        use_root_cause: 是否启用 Root Cause 对称分析 (默认 True)

    Returns:
        成功索引的 commit 数量
    """
    if not commits:
        return 0

    total = len(commits)
    client = get_milvus_client(dim=dim)

    # 1. 初始化 Collection
    if create_collection:
        client.create_collection(dim=dim)

    # 2. 准备文本 (传递 use_root_cause 参数)
    texts = [prepare_embedding_text(c, use_root_cause=use_root_cause) for c in commits]

    # 3. 准备元数据
    metadata_list = []
    for c in commits:
        if hasattr(c, "to_dict"):
            metadata_list.append(c.to_dict())
        else:
            metadata_list.append({"raw": str(c)[:256]})

    # 4. 分批向量化 + 插入
    encoder = get_encoder()
    inserted = 0
    encode_batch = batch_size
    insert_batch = 1000  # Milvus 建议每次插入 1k-10k 条

    for start in range(0, total, insert_batch):
        end = min(start + insert_batch, total)
        batch_texts = texts[start:end]
        batch_meta = metadata_list[start:end]

        # 分批编码
        vectors = encoder.encode(
            batch_texts,
            batch_size=encode_batch,
            show_progress=show_progress,
        )

        # 插入
        client.insert(vectors, batch_meta, batch_size=1000)
        inserted += len(batch_texts)

        if progress_callback:
            progress_callback(end, total)

    # 5. 持久化 (FAISS 模式)
    client.save()

    return inserted


def index_commits_incremental(
    new_commits: List[Any],
    batch_size: int = 64,
    dim: int = 1024,
    use_root_cause: bool = True,
) -> int:
    """增量索引：只处理新增的 commit

    与 index_commits 的区别:
    - 不重建 Collection（create_collection=False）
    - 只编码和插入新数据
    - 适合持续集成/定期同步场景

    Args:
        new_commits: 新增的 CommitInfo 列表
        batch_size: 向量化批量大小
        dim: 向量维度
        use_root_cause: 是否启用 Root Cause 对称分析 (默认 True)

    Returns:
        成功索引的 commit 数量
    """
    return index_commits(
        commits=new_commits,
        batch_size=batch_size,
        create_collection=False,
        dim=dim,
        use_root_cause=use_root_cause,
    )


# ============================================================================
# 在线查询流水线
# ============================================================================

def get_query_vector(
    analysis_result: Any,
    dim: int = 1024,
) -> np.ndarray:
    """在线流程：将分析结果转换为查询向量

    优先使用 RootCauseResult 的 retrieval_query 字段，
    fallback 到 prepare_embedding_text 通用方法。

    Args:
        analysis_result: RootCauseResult 或其他分析结果对象
        dim: 向量维度

    Returns:
        shape (dim,) 的 float32 查询向量
    """
    _ = dim  # 目前主要由全局 encoder 决定维度
    text = prepare_embedding_text(analysis_result)
    vector = encode_text([text])[0]
    return vector


def search_similar_commits(
    analysis_result: Any,
    top_k: int = 10,
    filter_expr: Optional[str] = None,
    dim: int = 1024,
) -> SearchResult:
    """一站式在线查询：从分析结果到候选 commit 列表

    完整的在线查询链路: 分析结果 → embedding → Milvus/FAISS 检索 → SearchResult

    Args:
        analysis_result: RootCauseResult 或查询文本
        top_k: 返回的候选数量
        filter_expr: 标量过滤表达式，如 'subsystem=="mm" && bug_type=="deadlock"'
        dim: 向量维度

    Returns:
        SearchResult 对象，包含候选 commit 的 ID、距离、元数据

    Example:
        >>> from src.analyzer import abstract_root_cause
        >>> from src.indexer import search_similar_commits
        >>> result = abstract_root_cause(feature)
        >>> hits = search_similar_commits(result, top_k=20)
        >>> for item in hits.to_dict_list():
        ...     print(f"{item['subject']}: score={item['score']:.3f}")
    """
    query_vec = get_query_vector(analysis_result, dim=dim)
    client = get_milvus_client(dim=dim)
    return client.search(query_vec, top_k=top_k, filter_expr=filter_expr)


# ============================================================================
# 索引统计
# ============================================================================

def get_index_stats() -> dict:
    """获取索引统计信息"""
    client = get_milvus_client()
    return client.get_stats()


def get_index_count() -> int:
    """获取已索引的向量总数"""
    client = get_milvus_client()
    return client.count()


__all__ = [
    # 文本准备
    "prepare_embedding_text",
    "prepare_commit_embedding_text",
    "prepare_rootcause_embedding_text",
    # 对称分析 (新增)
    "_commit_to_crash_feature",
    "_enhance_fix_hints_with_diff",
    "_build_commit_root_cause_embedding_text",
    # 离线索引
    "index_commits",
    "index_commits_incremental",
    # 在线查询
    "get_query_vector",
    "search_similar_commits",
    # 统计
    "get_index_stats",
    "get_index_count",
]
