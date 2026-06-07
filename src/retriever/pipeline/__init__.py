"""检索流水线模块 — End-to-End Retrieval Pipeline

四阶段检索架构的完整编排层，串联 Recall → Filter → Rerank → LLM Judge。

核心流程:
1. Phase 1 — Vector Recall: 从 Milvus/FAISS 中召回 Top-K 候选
2. Phase 2 — Rule Filter: 基于子系统/版本/关键词的硬过滤
3. Phase 3 — BGE Rerank: 交叉编码器深度语义重排
4. Phase 4 — LLM Judge: 大模型因果关联最终评分

支持三种检索模式:
- fast: 仅 Recall + Filter (毫秒级)
- standard: Recall + Filter + Rerank (秒级)
- deep: Recall + Filter + Rerank + LLM Judge (秒-分钟级)
"""

from __future__ import annotations
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from ..recall import recall_candidates, recall_from_rootcause, SearchResult
from ..filter import apply_filters, build_milvus_filter_expr
from ..rerank import rerank_candidates, RankedItem, RankedResult


# ============================================================================
# 检索模式
# ============================================================================

class RetrievalMode:
    FAST = "fast"          # Recall + Filter (毫秒级)
    STANDARD = "standard"  # Recall + Filter + Rerank (秒级)
    DEEP = "deep"          # Recall + Filter + Rerank + LLM Judge (秒-分钟级)


# ============================================================================
# 结果数据结构
# ============================================================================

@dataclass
class RetrievalResult:
    """在线检索的最终输出

    包含完整的检索链路信息和可解释的排序结果。
    """
    # 输入信息
    query_text: str = ""
    retrieval_mode: str = RetrievalMode.STANDARD

    # 阶段性结果
    recall_count: int = 0            # 向量召回数量
    after_filter_count: int = 0      # 过滤后数量
    final_count: int = 0             # 最终结果数量

    # 排序结果
    ranked_items: List[RankedItem] = field(default_factory=list)

    # 性能指标
    recall_time_ms: float = 0.0
    filter_time_ms: float = 0.0
    rerank_time_ms: float = 0.0
    total_time_ms: float = 0.0

    # 元信息
    metadata: Dict[str, Any] = field(default_factory=dict)

    def top(self, k: int = 10) -> List[RankedItem]:
        """返回 Top-K 结果"""
        return self.ranked_items[:k]

    def best(self) -> Optional[RankedItem]:
        """返回最佳匹配"""
        return self.ranked_items[0] if self.ranked_items else None

    def to_summary(self) -> Dict[str, Any]:
        """生成可读的摘要信息"""
        return {
            "retrieval_mode": self.retrieval_mode,
            "recall_count": self.recall_count,
            "after_filter_count": self.after_filter_count,
            "final_count": self.final_count,
            "total_time_ms": round(self.total_time_ms, 2),
            "top_hits": [
                {
                    "rank": item.rank,
                    "commit_hash": item.commit_hash,
                    "subject": item.subject,
                    "subsystem": item.subsystem,
                    "bug_type": item.bug_type,
                    "final_score": round(item.final_score, 4),
                    "rank_reason": item.rank_reason,
                }
                for item in self.ranked_items[:5]
            ],
        }

    def to_dict(self) -> Dict[str, Any]:
        """完整输出"""
        return {
            "query_text": self.query_text,
            "retrieval_mode": self.retrieval_mode,
            "recall_count": self.recall_count,
            "after_filter_count": self.after_filter_count,
            "final_count": self.final_count,
            "total_time_ms": round(self.total_time_ms, 2),
            "timing": {
                "recall_ms": round(self.recall_time_ms, 2),
                "filter_ms": round(self.filter_time_ms, 2),
                "rerank_ms": round(self.rerank_time_ms, 2),
            },
            "ranked_items": [
                {
                    "rank": item.rank,
                    "commit_hash": item.commit_hash,
                    "subject": item.subject,
                    "subsystem": item.subsystem,
                    "bug_type": item.bug_type,
                    "vector_score": round(item.vector_score, 4),
                    "reranker_score": round(item.reranker_score, 4),
                    "llm_judge_score": round(item.llm_judge_score, 4),
                    "final_score": round(item.final_score, 4),
                    "rank_reason": item.rank_reason,
                    "causal_relevance": item.causal_relevance,
                }
                for item in self.ranked_items
            ],
            "metadata": self.metadata,
        }


# ============================================================================
# 检索流水线核心
# ============================================================================

def run_retrieval_pipeline(
    rootcause_result,
    mode: str = RetrievalMode.STANDARD,
    top_k: int = 100,
    rerank_top_k: int = 50,
    filter_expr: Optional[str] = None,
    use_llm_judge: Optional[bool] = None,
) -> RetrievalResult:
    """运行完整的在线检索流水线

    这是整个在线检索系统的核心入口 — 从根因分析结果到最终排序的补丁推荐。

    四阶段架构:
    Phase 1: Vector Recall (向量召回)
        - 将 retrieval_query 用 BGE-M3 编码
        - Milvus/FAISS Top-K 语义召回
    Phase 2: Rule Filter (规则过滤)
        - 子系统/版本/关键词硬过滤
        - 安全补丁加权
    Phase 3: BGE Rerank (语义重排)
        - BGE-Reranker-v2 交叉编码
        - query-document 细粒度交互语义
    Phase 4: LLM Judge (因果评分) [仅在 deep 模式]
        - DeepSeek/Qwen 大模型因果关联推理
        - 多维度评分融合

    Args:
        rootcause_result: RootCauseResult 对象 (来自 analyzer)
        mode: 检索模式 — "fast" / "standard" / "deep"
        top_k: 向量召回的候选数
        rerank_top_k: 送入 Reranker 的候选数 (≤ top_k)
        filter_expr: 额外的 Milvus 过滤表达式
        use_llm_judge: 是否启用 LLM Judge (None 时由 mode 决定)

    Returns:
        RetrievalResult 对象

    Example:
        >>> from src.analyzer import run_analysis_pipeline
        >>> from src.retriever import run_retrieval_pipeline
        >>>
        >>> # Step 1: 分析宕机日志
        >>> analysis = run_analysis_pipeline(dmesg_content=dmesg_log)
        >>>
        >>> # Step 2: 在线检索匹配的补丁
        >>> result = run_retrieval_pipeline(
        ...     analysis,
        ...     mode="standard",
        ...     top_k=100,
        ... )
        >>>
        >>> # Step 3: 查看推荐结果
        >>> for item in result.top(5):
        ...     print(f"#{item.rank} [{item.subsystem}] {item.subject}")
        ...     print(f"   Score: {item.final_score:.3f} | {item.rank_reason}")
    """
    t_start = time.time()

    # 确定 LLM Judge 策略
    if use_llm_judge is None:
        use_llm_judge = (mode == RetrievalMode.DEEP)

    # 提取查询信息
    query_text = getattr(rootcause_result, "retrieval_query", "")
    if not query_text:
        from ...indexer.pipeline import prepare_rootcause_embedding_text
        query_text = prepare_rootcause_embedding_text(rootcause_result)

    feature = getattr(rootcause_result, "crash_feature", None)
    target_subsystem = getattr(feature, "subsystem", "unknown") if feature else "unknown"
    target_bug_type = getattr(rootcause_result, "bug_type", "unknown")
    kernel_version = getattr(feature, "kernel_version", "") if feature else ""

    result = RetrievalResult(
        query_text=query_text,
        retrieval_mode=mode,
    )

    # ── Phase 1: Vector Recall ─────────────────────────────────
    t_recall = time.time()
    search_result = recall_from_rootcause(
        rootcause_result,
        top_k=top_k,
        filter_expr=filter_expr,
    )
    candidates = search_result.to_dict_list()
    result.recall_count = len(candidates)
    result.recall_time_ms = (time.time() - t_recall) * 1000

    if not candidates:
        result.total_time_ms = (time.time() - t_start) * 1000
        return result

    # ── Phase 2: Rule Filter ───────────────────────────────────
    t_filter = time.time()
    candidates = apply_filters(
        candidates,
        target_subsystem=target_subsystem,
        target_bug_type=target_bug_type,
        kernel_version=kernel_version,
        boost_security=True,
    )
    result.after_filter_count = len(candidates)
    result.filter_time_ms = (time.time() - t_filter) * 1000

    if not candidates:
        result.total_time_ms = (time.time() - t_start) * 1000
        return result

    # ── Fast 模式在此返回 ──────────────────────────────────────
    if mode == RetrievalMode.FAST:
        vector_scores = [c.get("score", 0.5) for c in candidates]
        for i, cand in enumerate(candidates):
            item = RankedItem(
                rank=i + 1,
                commit_hash=cand.get("commit_hash", ""),
                subject=cand.get("subject", ""),
                subsystem=cand.get("subsystem", "unknown"),
                bug_type=cand.get("bug_type", "unknown"),
                vector_score=vector_scores[i],
                final_score=vector_scores[i],
                metadata=cand,
            )
            result.ranked_items.append(item)
        result.final_count = len(result.ranked_items)
        result.total_time_ms = (time.time() - t_start) * 1000
        return result

    # ── Phase 3: BGE Rerank ────────────────────────────────────
    t_rerank = time.time()
    rerank_candidates = candidates[:rerank_top_k]
    vector_scores = [c.get("_boosted_score", c.get("score", 0.5)) for c in rerank_candidates]

    ranked_result = rerank_candidates(
        query_text=query_text,
        candidates=rerank_candidates,
        vector_scores=vector_scores,
        use_llm_judge=use_llm_judge,
    )
    result.ranked_items = ranked_result.items
    result.final_count = len(ranked_result.items)
    result.rerank_time_ms = ranked_result.rerank_time_ms

    # ── 元信息 ─────────────────────────────────────────────────
    result.metadata = {
        "target_subsystem": target_subsystem,
        "target_bug_type": target_bug_type,
        "kernel_version": kernel_version,
        "retrieval_mode": mode,
        "use_llm_judge": use_llm_judge,
        "filter_expr": filter_expr,
    }

    result.total_time_ms = (time.time() - t_start) * 1000
    return result


# ============================================================================
# 便捷函数
# ============================================================================

def quick_search(
    query_text: str,
    top_k: int = 20,
    mode: str = RetrievalMode.FAST,
) -> RetrievalResult:
    """快速检索 — 从文本直接搜索，不经过分析流水线

    适用场景:
    - 已知 Bug 类型/子系统，直接搜索相关补丁
    - 运维人员手动输入关键词快速查找

    Args:
        query_text: 查询文本
        top_k: 返回数量
        mode: 检索模式

    Returns:
        RetrievalResult 对象

    Example:
        >>> hits = quick_search("use after free in net/tcp.c", top_k=10)
        >>> for item in hits.top(5):
        ...     print(item.subject)
    """
    from ...analyzer.models import CrashFeature, RootCauseResult

    # 构造临时 RootCauseResult
    feature = CrashFeature(panic_msg=query_text)
    temp_result = RootCauseResult(
        crash_feature=feature,
        retrieval_query=query_text,
        root_cause="Manual query",
    )

    return run_retrieval_pipeline(
        temp_result,
        mode=mode,
        top_k=top_k,
        rerank_top_k=min(top_k, 50),
    )


def search_by_bug_type(
    bug_type: str,
    subsystem: str = "unknown",
    top_k: int = 50,
) -> RetrievalResult:
    """按 Bug 类型搜索 — 快速定位特定类型问题的已知修复

    Args:
        bug_type: Bug 类型 (如 "use_after_free", "deadlock")
        subsystem: 子系统过滤 (可选)
        top_k: 返回数量

    Returns:
        RetrievalResult 对象
    """
    query_text = f"RootCause: {bug_type.replace('_', ' ')}\nBugType: {bug_type}"
    if subsystem != "unknown":
        query_text += f"\nSubsystem: {subsystem}"

    filter_expr = None
    if subsystem != "unknown":
        filter_expr = build_milvus_filter_expr(subsystem=subsystem, bug_type=bug_type)

    from ...analyzer.models import CrashFeature, RootCauseResult
    feature = CrashFeature(subsystem=subsystem, bug_type=bug_type)
    temp_result = RootCauseResult(
        crash_feature=feature,
        retrieval_query=query_text,
        root_cause=bug_type.replace("_", " ").title(),
    )

    return run_retrieval_pipeline(
        temp_result,
        mode=RetrievalMode.STANDARD,
        top_k=top_k,
        filter_expr=filter_expr,
    )


__all__ = [
    # 数据结构
    "RetrievalResult",
    "RetrievalMode",
    # 核心流水线
    "run_retrieval_pipeline",
    # 便捷函数
    "quick_search",
    "search_by_bug_type",
]
