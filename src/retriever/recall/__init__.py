"""向量召回模块 — Vector Recall Engine

负责从向量数据库中进行 Top-K 候选召回，是在线检索的第一阶段。
支持 Milvus (生产) 和 FAISS (本地开发) 双后端。

核心功能:
- 基于 RootCauseResult.retrieval_query 的 BGE-M3 向量编码
- Milvus/FAISS Top-K 向量相似度召回
- 混合检索: 向量相似度 + 标量过滤 (按子系统/版本/日期)
- 批量查询支持

设计要点:
- 利用 Analyzer 输出的 retrieval_query（6层语义融合），作为查询向量
- 支持 filter_expr 进行子系统/版本的硬过滤
- 自动降级: Milvus 不可用时切换到 FAISS 本地模式
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Any, Optional

from ...indexer.embedding import encode_text, get_encoder
from ...indexer.milvus import get_milvus_client, SearchResult


def encode_query(
    query_text: str,
    normalize: bool = True,
) -> np.ndarray:
    """将查询文本编码为向量

    支持直接传入 retrieval_query 文本（推荐）
    或任意自然语言查询。

    Args:
        query_text: 查询文本，推荐使用 RootCauseResult.retrieval_query
        normalize: 是否归一化 (默认 True，确保余弦相似度精度)

    Returns:
        shape (dim,) 的 float32 查询向量
    """
    vec = encode_text([query_text])[0]
    if normalize:
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
    return vec


def recall_candidates(
    query_text: str,
    top_k: int = 100,
    filter_expr: Optional[str] = None,
    dim: int = 1024,
) -> SearchResult:
    """从向量库中召回 Top-K 候选 commit

    这是在线检索的第一阶段 — 快速语义召回。
    后续经过 Rerank 和 LLM Judge 进一步精排。

    Args:
        query_text: 查询文本，推荐直接传入 RootCauseResult.retrieval_query
        top_k: 召回的候选数量 (建议 50-200)
        filter_expr: Milvus 标量过滤表达式
            例如: 'subsystem=="mm" && bug_type=="deadlock"'
        dim: 向量维度 (默认 1024, BGE-M3)

    Returns:
        SearchResult 对象 — 包含候选 commit 的 id/distance/metadata

    Example:
        >>> from src.analyzer import run_analysis_pipeline
        >>> from src.retriever.recall import recall_candidates
        >>> result = run_analysis_pipeline(dmesg_content=dmesg_log)
        >>> hits = recall_candidates(
        ...     result.retrieval_query,
        ...     top_k=100,
        ...     filter_expr='subsystem=="mm"',
        ... )
        >>> for item in hits.to_dict_list()[:5]:
        ...     print(f"{item['subject']}: {item['score']:.3f}")
    """
    query_vec = encode_query(query_text)

    client = get_milvus_client(dim=dim)
    return client.search(
        query_vec,
        top_k=top_k,
        filter_expr=filter_expr,
    )


def recall_from_rootcause(
    rootcause_result,
    top_k: int = 100,
    filter_expr: Optional[str] = None,
) -> SearchResult:
    """从 RootCauseResult 直接召回候选

    自动使用 rootcause_result.retrieval_query 作为查询文本。
    这是推荐的使用方式 — 保证查询文本与索引时的 embedding_text 结构对称。

    Args:
        rootcause_result: RootCauseResult 对象 (来自 analyzer)
        top_k: 召回数量
        filter_expr: 标量过滤表达式

    Returns:
        SearchResult 对象
    """
    query_text = getattr(rootcause_result, "retrieval_query", "")
    if not query_text:
        # 降级: 从字段拼接
        from ...indexer.pipeline import prepare_rootcause_embedding_text
        query_text = prepare_rootcause_embedding_text(rootcause_result)

    # 自动添加子系统过滤 (如果识别出子系统)
    if filter_expr is None:
        feature = getattr(rootcause_result, "crash_feature", None)
        if feature:
            subsys = getattr(feature, "subsystem", "unknown")
            if subsys and subsys != "unknown":
                filter_expr = f'subsystem=="{subsys}"'

    return recall_candidates(query_text, top_k=top_k, filter_expr=filter_expr)


def batch_recall(
    query_texts: List[str],
    top_k: int = 100,
    filter_expr: Optional[str] = None,
) -> List[SearchResult]:
    """批量召回 — 多个查询同时执行

    Args:
        query_texts: 查询文本列表
        top_k: 每个查询的召回数量
        filter_expr: 统一的标量过滤 (或 None)

    Returns:
        SearchResult 列表，与输入顺序一致
    """
    results = []
    for text in query_texts:
        result = recall_candidates(text, top_k=top_k, filter_expr=filter_expr)
        results.append(result)
    return results


def get_recall_stats(result: SearchResult) -> Dict[str, Any]:
    """获取召回统计信息

    Args:
        result: SearchResult 对象

    Returns:
        包含 hit_count, avg_distance, subsystems, bug_types 的字典
    """
    if not result or len(result) == 0:
        return {
            "hit_count": 0,
            "avg_distance": 0.0,
            "subsystems": [],
            "bug_types": [],
        }

    subsys_counter: Dict[str, int] = {}
    bugtype_counter: Dict[str, int] = {}

    for meta in result.metadata:
        subsys = meta.get("subsystem", "unknown")
        bugtype = meta.get("bug_type", "unknown")
        subsys_counter[subsys] = subsys_counter.get(subsys, 0) + 1
        bugtype_counter[bugtype] = bugtype_counter.get(bugtype, 0) + 1

    return {
        "hit_count": len(result),
        "avg_distance": np.mean(result.distances) if result.distances else 0.0,
        "subsystems": sorted(subsys_counter.items(), key=lambda x: -x[1]),
        "bug_types": sorted(bugtype_counter.items(), key=lambda x: -x[1]),
        "search_time_ms": result.search_time_ms,
    }


__all__ = [
    "encode_query",
    "recall_candidates",
    "recall_from_rootcause",
    "batch_recall",
    "get_recall_stats",
]
