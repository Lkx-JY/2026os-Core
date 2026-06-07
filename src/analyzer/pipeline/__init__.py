"""分析流水线模块 — Unified Analysis Pipeline

负责协调 dmesg/vmcore 解析和根因抽象的完整流程。

支持三种输入模式:
1. vmcore + dmesg (最优): vmcore 深度解析为主，dmesg 补充 Call Trace
2. vmcore only: 从 vmcore 提取所有可用特征
3. dmesg only: 从 dmesg 日志提取特征并分析

支持两种分析模式:
1. rule_only: 仅使用 28 条专家规则 (快速、确定性)
2. hybrid: 专家规则 + LLM 协同分析 (更准确、更可读)
"""

from typing import Optional
from ..models import CrashFeature, RootCauseResult
from ..dmesg import parse_dmesg, parse_dmesg_with_llm
from ..vmcore import analyze_vmcore, fuse_features
from ..rootcause import abstract_root_cause


def run_analysis_pipeline(
    dmesg_content: Optional[str] = None,
    vmcore_path: Optional[str] = None,
    vmlinux_path: Optional[str] = None,
    use_llm: bool = False,
    model_name: str = "deepseek-chat",
) -> RootCauseResult:
    """运行完整分析流水线

    流水线阶段:
    Phase 1 (特征提取):
        - vmcore 优先: 使用 drgn 从 vmcore 提取内核对象、寄存器、调用栈
        - dmesg 补充: 从 dmesg 提取 Call Trace 和 Panic 消息
        - [可选] LLM 深度分析 dmesg
    Phase 2 (根因抽象):
        - [默认] 专家规则匹配 (28 条规则)
        - [可选] LLM + 专家规则协同分析 (hybrid mode)
        - 修复模式推断
        - 检索查询构造

    Args:
        dmesg_content: dmesg 日志文本内容 (可选)
        vmcore_path: vmcore 文件路径 (可选)
        vmlinux_path: 对应的 vmlinux 文件路径 (可选，vmcore 解析需要)
        use_llm: 是否启用 LLM 增强分析
        model_name: LLM 模型名称 (仅 use_llm=True 时有效)

    Returns:
        RootCauseResult: 包含根因诊断、因果链、置信度评分、检索查询等

    Example:
        >>> # 仅使用规则
        >>> result = run_analysis_pipeline(dmesg_content="BUG: list_del corruption...")
        >>> print(result.root_cause)       # "Memory Corruption (List)"
        >>> print(result.score)            # 0.85
        >>>
        >>> # 使用 LLM 增强
        >>> result = run_analysis_pipeline(
        ...     dmesg_content=dmesg_log,
        ...     vmcore_path="/path/to/vmcore",
        ...     use_llm=True,
        ... )
        >>> print(result.retrieval_query)  # LLM 优化后的检索查询
    """

    feature = CrashFeature()

    # ── Phase 1: 特征提取 ──────────────────────────────────────
    if vmcore_path:
        # 优先使用 vmcore 进行深度解析
        feature = analyze_vmcore(vmcore_path, vmlinux_path or "")

        # 如果同时提供了 dmesg，补充 Call Trace 和 Panic 消息
        if dmesg_content:
            if use_llm:
                dmesg_feature = parse_dmesg_with_llm(
                    dmesg_content,
                    use_llm=True,
                    model_name=model_name,
                )
            else:
                dmesg_feature = parse_dmesg(dmesg_content)

            # 融合 vmcore + dmesg 特征
            feature = fuse_features(feature, dmesg_feature)

    elif dmesg_content:
        # 仅使用 dmesg 进行解析
        if use_llm:
            feature = parse_dmesg_with_llm(
                dmesg_content,
                use_llm=True,
                model_name=model_name,
            )
        else:
            feature = parse_dmesg(dmesg_content)

    # ── Phase 2: 根因抽象 ──────────────────────────────────────
    if use_llm:
        from ..rootcause.llm_rootcause import hybrid_root_cause_analysis
        result = hybrid_root_cause_analysis(
            feature,
            use_llm=True,
            model_name=model_name,
        )
    else:
        result = abstract_root_cause(feature)

    return result


__all__ = [
    "run_analysis_pipeline",
]
