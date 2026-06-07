"""业务逻辑编排层 — Online Service Orchestration

负责串联"特征提取 → 根因抽象 → 向量编码 → 在线检索 → 结果生成"的全链路流程。
是连接各子模块的业务编排层。
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from ..analyzer import (
    CrashFeature,
    RootCauseResult,
    run_analysis_pipeline,
)
from ..indexer import (
    get_query_vector,
)
from ..retriever import (
    RetrievalResult,
    RetrievalMode,
    run_retrieval_pipeline,
    RankedItem,
)


# ============================================================================
# 在线服务结果
# ============================================================================

@dataclass
class OnlineDiagnosisResult:
    """完整的在线诊断结果 — 从输入到补丁推荐的端到端输出"""
    # 输入
    dmesg_content: str = ""
    vmcore_path: str = ""

    # 分析结果
    crash_feature: Optional[CrashFeature] = None
    root_cause_result: Optional[RootCauseResult] = None

    # 检索结果
    retrieval_result: Optional[RetrievalResult] = None

    # 查询向量 (1024-dim float32)
    query_vector: Optional[Any] = None

    # 元信息
    total_time_ms: float = 0.0
    analysis_mode: str = "rule_only"
    status: str = "pending"
    error_message: str = ""

    def to_summary(self) -> Dict[str, Any]:
        """生成可读的诊断摘要"""
        summary: Dict[str, Any] = {
            "status": self.status,
            "analysis_mode": self.analysis_mode,
            "total_time_ms": round(self.total_time_ms, 2),
        }

        if self.root_cause_result:
            summary["root_cause"] = self.root_cause_result.root_cause
            summary["bug_type"] = self.root_cause_result.bug_type
            summary["confidence"] = round(self.root_cause_result.score, 3)
            summary["retrieval_query"] = self.root_cause_result.retrieval_query[:200]

        if self.retrieval_result:
            summary["recommendations"] = [
                {
                    "rank": item.rank,
                    "commit_hash": item.commit_hash,
                    "subject": item.subject,
                    "score": round(item.final_score, 3),
                }
                for item in self.retrieval_result.top(10)
            ]

        if self.error_message:
            summary["error"] = self.error_message

        return summary

    def to_dict(self) -> Dict[str, Any]:
        """完整输出"""
        result = self.to_summary()
        if self.root_cause_result:
            result["analysis"] = {
                "root_cause": self.root_cause_result.root_cause,
                "bug_type": self.root_cause_result.bug_type,
                "causal_chain": self.root_cause_result.causal_chain,
                "score": self.root_cause_result.score,
                "reason": self.root_cause_result.reason,
                "suggested_keywords": self.root_cause_result.suggested_keywords,
                "retrieval_query": self.root_cause_result.retrieval_query,
            }
        if self.retrieval_result:
            result["retrieval"] = self.retrieval_result.to_dict()
        return result


# ============================================================================
# 在线诊断服务
# ============================================================================

def run_online_diagnosis(
    dmesg_content: Optional[str] = None,
    vmcore_path: Optional[str] = None,
    vmlinux_path: Optional[str] = None,
    use_llm: bool = False,
    model_name: str = "deepseek-chat",
    retrieval_mode: str = RetrievalMode.STANDARD,
    top_k: int = 100,
) -> OnlineDiagnosisResult:
    """运行完整的在线诊断流程

    全链路流程:
    Step 1 → Feature Extraction (dmesg regex + optional LLM + vmcore drgn)
    Step 2 → Root Cause Abstraction (28 rules + optional LLM hybrid)
    Step 3 → Embedding Encoding (BGE-M3 → 1024d vector)
    Step 4 → Vector Retrieval (Milvus/FAISS Top-K recall)
    Step 5 → Multi-stage Ranking (Filter → BGE Rerank → optional LLM Judge)

    Args:
        dmesg_content: dmesg 日志内容
        vmcore_path: vmcore 文件路径
        vmlinux_path: vmlinux 文件路径 (vmcore 解析需要)
        use_llm: 是否启用 LLM 增强分析
        model_name: LLM 模型名称
        retrieval_mode: 检索模式 (fast/standard/deep)
        top_k: 向量召回数量

    Returns:
        OnlineDiagnosisResult — 包含完整诊断和补丁推荐

    Example:
        >>> from src.services import run_online_diagnosis
        >>> result = run_online_diagnosis(
        ...     dmesg_content=dmesg_log,
        ...     vmcore_path="/path/to/vmcore",
        ...     use_llm=True,
        ...     retrieval_mode="standard",
        ... )
        >>> print(result.to_summary())
        >>> for item in result.retrieval_result.top(5):
        ...     print(f"#{item.rank}: {item.subject}")
    """
    import time
    t_start = time.time()

    result = OnlineDiagnosisResult(
        dmesg_content=dmesg_content or "",
        vmcore_path=vmcore_path or "",
        analysis_mode="hybrid" if use_llm else "rule_only",
    )

    try:
        # ── Step 1+2: 特征提取 + 根因抽象 ──────────────────────
        root_cause = run_analysis_pipeline(
            dmesg_content=dmesg_content,
            vmcore_path=vmcore_path,
            vmlinux_path=vmlinux_path,
            use_llm=use_llm,
            model_name=model_name,
        )
        result.root_cause_result = root_cause
        result.crash_feature = root_cause.crash_feature

        # ── Step 3: Embedding 编码 (BGE-M3 向量化) ──────────
        query_vector = get_query_vector(root_cause)
        result.query_vector = query_vector

        # ── Step 4+5: 在线检索 + 多阶段排序 ─────────────────
        retrieval = run_retrieval_pipeline(
            root_cause,
            mode=retrieval_mode,
            top_k=top_k,
        )
        result.retrieval_result = retrieval

        result.status = "completed"

    except Exception as e:
        result.status = "error"
        result.error_message = str(e)

    result.total_time_ms = (time.time() - t_start) * 1000
    return result


def encode_root_cause_for_search(
    root_cause_result: RootCauseResult,
) -> Any:
    """对根因抽象结果进行 Embedding 编码（向量化）

    使用 BGE-M3 将 retrieval_query 编码为 1024 维向量。
    这是连接"根因分析"与"向量检索"的关键编码步骤。

    Args:
        root_cause_result: RootCauseResult 对象

    Returns:
        np.ndarray — shape (1024,) 的 float32 查询向量

    Example:
        >>> from src.analyzer import abstract_root_cause, parse_dmesg
        >>> from src.services import encode_root_cause_for_search
        >>> feature = parse_dmesg(dmesg_log)
        >>> result = abstract_root_cause(feature)
        >>> query_vec = encode_root_cause_for_search(result)
        >>> print(query_vec.shape)  # (1024,)
    """
    return get_query_vector(root_cause_result)


def batch_diagnosis(
    dmesg_list: List[str],
    use_llm: bool = False,
    top_k: int = 50,
) -> List[OnlineDiagnosisResult]:
    """批量在线诊断

    Args:
        dmesg_list: dmesg 日志列表
        use_llm: 是否启用 LLM
        top_k: 每个查询的召回数

    Returns:
        OnlineDiagnosisResult 列表
    """
    results = []
    for dmesg in dmesg_list:
        result = run_online_diagnosis(
            dmesg_content=dmesg,
            use_llm=use_llm,
            retrieval_mode=RetrievalMode.FAST,
            top_k=top_k,
        )
        results.append(result)
    return results


__all__ = [
    # 数据结构
    "OnlineDiagnosisResult",
    # 核心服务
    "run_online_diagnosis",
    "encode_root_cause_for_search",
    "batch_diagnosis",
]
