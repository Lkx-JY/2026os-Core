"""在线检索模块 — Online Retrieval System

四阶段检索架构的核心实现，负责从向量库中检索与宕机分析结果匹配的补丁。

整合了以下功能:
- recall: 向量召回 (Milvus/FAISS Top-K)
- filter: 规则过滤 (子系统/版本/关键词)
- rerank: 深度重排 (BGE-Reranker-v2 + LLM Judge)
- pipeline: 检索流水线编排 (end-to-end)

完整的在线检索链路:
    dmesg/vmcore → CrashFeature → RootCauseResult
    → Recall (Top-100) → Filter → Rerank (Top-20) → LLM Judge
    → 最终推荐结果
"""

from .recall import (
    encode_query,
    recall_candidates,
    recall_from_rootcause,
    batch_recall,
    get_recall_stats,
)
from .filter import (
    FilterResult,
    filter_by_subsystem,
    filter_by_bug_type,
    filter_by_kernel_version,
    filter_duplicates,
    filter_by_keywords,
    boost_security_fixes,
    apply_filters,
    build_milvus_filter_expr,
)
from .rerank import (
    RankedItem,
    RankedResult,
    BGEReranker,
    get_reranker,
    llm_judge_scores,
    fuse_scores,
    rerank_candidates,
)
from .pipeline import (
    RetrievalResult,
    RetrievalMode,
    run_retrieval_pipeline,
    quick_search,
    search_by_bug_type,
)

__all__ = [
    # Recall
    "encode_query",
    "recall_candidates",
    "recall_from_rootcause",
    "batch_recall",
    "get_recall_stats",
    # Filter
    "FilterResult",
    "filter_by_subsystem",
    "filter_by_bug_type",
    "filter_by_kernel_version",
    "filter_duplicates",
    "filter_by_keywords",
    "boost_security_fixes",
    "apply_filters",
    "build_milvus_filter_expr",
    # Rerank
    "RankedItem",
    "RankedResult",
    "BGEReranker",
    "get_reranker",
    "llm_judge_scores",
    "fuse_scores",
    "rerank_candidates",
    # Pipeline
    "RetrievalResult",
    "RetrievalMode",
    "run_retrieval_pipeline",
    "quick_search",
    "search_by_bug_type",
]
