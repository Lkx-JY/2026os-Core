"""分析流水线模块

负责协调 dmesg/vmcore 解析和根因抽象的完整流程。
支持三种输入模式:
1. vmcore + dmesg (最优): vmcore 深度解析为主，dmesg 补充 Call Trace
2. vmcore only: 从 vmcore 提取所有可用特征
3. dmesg only: 从 dmesg 日志提取特征并分析
"""

from typing import Optional
from ..models import CrashFeature, RootCauseResult
from ..dmesg import parse_dmesg
from ..vmcore import analyze_vmcore
from ..rootcause import abstract_root_cause


def run_analysis_pipeline(
    dmesg_content: Optional[str] = None,
    vmcore_path: Optional[str] = None,
    vmlinux_path: Optional[str] = None,
) -> RootCauseResult:
    """运行完整分析流水线

    流水线阶段:
    Phase 1 (特征提取):
        - vmcore 优先: 使用 drgn 从 vmcore 提取内核对象、寄存器、调用栈
        - dmesg 补充: 从 dmesg 提取 Call Trace 和 Panic 消息
    Phase 2 (根因抽象):
        - 专家规则匹配 (20+ 规则)
        - 调用栈结构分析
        - 修复模式推断
        - 检索查询构造

    Args:
        dmesg_content: dmesg 日志文本内容 (可选)
        vmcore_path: vmcore 文件路径 (可选)
        vmlinux_path: 对应的 vmlinux 文件路径 (可选，vmcore 解析需要)

    Returns:
        RootCauseResult: 包含根因诊断、因果链、置信度评分、检索查询等完整信息

    Example:
        >>> result = run_analysis_pipeline(dmesg_content="BUG: list_del corruption...")
        >>> print(result.root_cause)       # "Memory Corruption (List)"
        >>> print(result.score)            # 0.85
        >>> print(result.retrieval_query)  # 优化后的检索查询
    """

    feature = CrashFeature()

    # Phase 1: 特征提取
    if vmcore_path:
        # 优先使用 vmcore 进行深度解析
        feature = analyze_vmcore(vmcore_path, vmlinux_path or "")

        # 如果同时提供了 dmesg，补充 Call Trace 和 Panic 消息
        if dmesg_content:
            dmesg_feature = parse_dmesg(dmesg_content)
            # 合并特征 (以 vmcore 为主，dmesg 补充)
            if not feature.call_trace:
                feature.call_trace = dmesg_feature.call_trace
            if not feature.panic_msg:
                feature.panic_msg = dmesg_feature.panic_msg
            # 如果 vmcore 没有解析出 subsystem/bug_type，使用 dmesg 的结果
            if feature.subsystem == "unknown":
                feature.subsystem = dmesg_feature.subsystem
            if feature.bug_type == "unknown":
                feature.bug_type = dmesg_feature.bug_type

    elif dmesg_content:
        # 仅使用 dmesg 进行解析
        feature = parse_dmesg(dmesg_content)

    # Phase 2: 根因抽象
    result = abstract_root_cause(feature)

    return result
